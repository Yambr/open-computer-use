# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# Copyright (c) 2025 Open Computer Use Contributors
#
# Gherkin scenarios for the four OCU MCP tools (bash_tool, str_replace,
# create_file, view), derived from the PoC behavior in
# computer-use-server/mcp_tools.py and routed onto the fleet path
# (OpenWebUI -> ocu-mcp-gateway ingress projection -> forward mTLS ->
# ocu-control -> gVisor guest exec).
#
# These are the source-of-truth scenarios. Each @level tag routes the
# scenario to where it is honest to prove it (Fable routing rule):
#   @L4  gateway internal/forward e2e — real create+exec hops, executing
#        control-mock runs the REAL committed projection scripts. Owns every
#        behavior decided AT OR ABOVE the exec contract (argv+stdin in ->
#        exit+stdout+stderr+truncation-flags out): projection, script
#        semantics, result shaping (exit->isError, stream->content).
#   @L5  deploy/tests/journeys — live Lima fleet, real gVisor guest. Owns
#        every behavior decided BELOW the exec contract: exit-code transport,
#        real truncation + flag, timeout enforcement, EACCES guest-identity,
#        and workspace persistence across calls.
#
# PoC behavior is quoted verbatim from mcp_tools.py so the fleet Then-clauses
# pin the same observable contract. Where the fleet intentionally diverges
# (HARDENED / guest-identity), the scenario says so and CONTRAST.md records it.

Feature: OCU MCP tool surface executes end-to-end

  Background:
    Given a cold chat session with a python3-bearing guest
    And the OCU tool is bound to the model (native function calling)

  # ===================================================================
  # bash_tool  (PoC: mcp_tools.py:474-537, docker_manager.py:940-989)
  # ===================================================================

  @L5 @bash @happy
  Scenario: bash_tool returns real guest stdout on the first cold call
    When the model calls bash_tool with command "echo <marker>"
    Then the CallToolResult is not an error
    And the decoded stdout contains the literal marker "<marker>"
    And the marker does NOT appear only base64-encoded
    # keystone: a base64 echo of the request would be a fake-green (H5 guard)

  @L4 @bash @error
  Scenario: non-zero exit with no output surfaces the exit code
    # The gateway synthesizes the PoC literal ONLY when both streams are empty
    # (mcp_tools.py:456). One shaping layer (gateway); control/guest never synthesize.
    When bash_tool runs "exit 7"
    Then the result has isError true
    And the result text is exactly "[Exit code: 7]"

  @L4 @bash @error
  Scenario: non-zero exit with stderr relays the stderr, not the marker
    When bash_tool runs "echo boom 1>&2; exit 3"
    Then the result has isError true
    And the result text is exactly "boom\n"

  @L4 @bash @error
  Scenario: non-zero exit with stdout-only relays the stdout
    When bash_tool runs "echo cause; exit 5"
    Then the result has isError true
    And the result text is exactly "cause\n"

  @L4 @bash @semantics
  Scenario: a bare grep no-match is informational, not a tool error (D8 parity)
    # PoC parity (D8): the gateway's COMMAND_SEMANTICS table restores the PoC
    # reading for a leading grep/rg whose only failure is exit 1 (no matches):
    # informational, isError false, rewritten to "No matches found". This
    # matches the PoC, which treated grep-exit-1 as informational.
    When bash_tool runs "grep needle /etc/hostname"
    Then the result has isError false
    And the result text is exactly "No matches found"

  @L4 @bash @contrast
  Scenario: the semantics table is first-command-only (compound scope pin)
    # Scope pin for the D8 table: it keys on the FIRST command of the bash argv,
    # so a COMPOUND command whose leading program is not grep/rg does NOT get the
    # informational rewrite. Here printf leads, so the grep-exit-1 tail surfaces
    # as the fleet's plain isError model -- the table never fires on the tail.
    When bash_tool runs "printf hay > /tmp/f && grep needle /tmp/f"
    Then the result has isError true
    And the result text is exactly "[Exit code: 1]"

  @L4 @bash @happy
  Scenario: zero exit with no output is a silent success (marker must not over-fire)
    When bash_tool runs "true"
    Then the result has isError false
    And the result text is exactly ""

  @L5 @bash @error
  Scenario: a real failing command transports its non-zero exit live
    When bash_tool runs "sh -c 'exit 3'" through the live fleet
    Then the CallToolResult is an error
    # closes the fabricated-exit-code debt: L2 mock invented the exit code;
    # this proves ocu-control really transports a non-zero exit from the guest

  @L4 @bash @streams
  Scenario: stdout and stderr land in their own fields (three-way probe)
    # THE anti-fake-green guard. Must red against a CombinedOutput mock.
    When bash_tool runs a command printing "OUT-<marker>" to stdout and "ERR-<marker>" to stderr and exiting 7
    Then the exit code is 7
    And the stdout field contains "OUT-<marker>" and NOT "ERR-<marker>"
    And the stderr field contains "ERR-<marker>" and NOT "OUT-<marker>"
    # keystone: a mock that fuses streams (CombinedOutput) fails this instantly

  @L5 @bash @truncation
  Scenario: oversized output is truncated and flagged by control
    When bash_tool emits more than the stdout truncation threshold
    Then the result carries the stdout_truncated flag
    And the body is bounded, not the full output
    # PoC caps at 30000 chars with a middle-omitted marker (mcp_tools.py:412,459)

  @L5 @bash @timeout
  Scenario: a command exceeding the timeout is killed by the guest
    When bash_tool runs a command that sleeps past the command timeout
    Then the result reports the command timed out
    # enforcement is BELOW the contract (guest/control kills), not the gateway

  # ===================================================================
  # str_replace  (PoC: mcp_tools.py:541-614, script 577-608)
  # ===================================================================

  @L4 @str_replace @happy
  Scenario: str_replace replaces a single unambiguous occurrence
    Given a file containing exactly one occurrence of "BRAVO"
    When str_replace replaces "BRAVO" with "DELTA"
    Then the result is not an error
    And the content says "Successfully replaced text in <path>"
    And the file now contains "DELTA"

  @L4 @str_replace @error
  Scenario Outline: str_replace refuses ambiguous or empty edits and projects isError
    # The composition L4 exists for: script exit-1 -> isError:true through forward.
    # L3 proved the script; L2 proved the projection; nothing proved them TOGETHER.
    When str_replace is called with <case>
    Then the CallToolResult is an error
    And the content contains "<message>"
    And the file is left unchanged

    Examples:
      | case                                  | message                          |
      | identical old_str and new_str         | identical                        |
      | an old_str that does not occur        | not found                        |
      | an old_str occurring more than once   | occurrences ... context          |

  # ===================================================================
  # create_file  (PoC: mcp_tools.py:618-674, script 648-667)
  # ===================================================================

  @L4 @create_file @happy
  Scenario: create_file writes the body and creates missing parents
    When create_file writes "hello" to "nested/deep/a.txt"
    Then the result is not an error
    And the content says "Successfully created <path>"
    And the parent directories were created
    And the file body is exactly "hello"

  @L4 @create_file @overwrite
  Scenario: create_file overwrites an existing file without a guard
    # TOTAL GAP today — behavior exists (open(path,'w')) but is untested at any level.
    Given a file "c.txt" already containing "OLD"
    When create_file writes "NEW" to "c.txt"
    Then the result is not an error
    And the content says "Successfully created c.txt"
    And the file body is exactly "NEW"
    # PoC gives no overwrite warning; this pins that the fleet matches (IDENTICAL)

  @L4 @create_file @error
  Scenario: create_file into a read-only directory errors with no partial write
    When create_file targets a path inside a read-only directory
    Then the CallToolResult is an error
    And the content surfaces the write failure
    And nothing was written at the target
    # already pinned at L3 (task #123); this raises it to the exec-contract level

  @L5 @create_file @identity
  Scenario: guest identity determines whether a protected path is writable
    # PoC-vs-fleet CONTRAST: EACCES depends on the guest's uid. If the fleet
    # guest runs as root it may NOT reproduce the PoC's EACCES on /home/assistant.
    When create_file targets a path the guest user cannot write
    Then the live outcome is recorded in CONTRAST.md against the PoC outcome

  # ===================================================================
  # view  (PoC: mcp_tools.py:678-812)
  # ===================================================================

  @L4 @view @happy
  Scenario: view shows a text file with line numbers
    Given a file with two lines
    When view is called on that file
    Then the result is not an error
    And each line is shown with a right-justified line number

  @L4 @view @dir
  Scenario: view lists a directory
    Given a directory containing a child entry
    When view is called on the directory
    Then the result is not an error
    And the child entry is listed

  @L4 @view @error
  Scenario: view of a missing path errors
    When view is called on a path that does not exist
    Then the CallToolResult is an error
    And the content says "not found"

  @L4 @view @binary
  Scenario: view of a non-text file does not crash
    # TOTAL GAP today. The committed viewScript decodes with errors='replace';
    # pin that a binary body is handled, not an exception.
    Given a file containing non-UTF8 bytes
    When view is called on that file
    Then the result is not an error
    And the content is returned without raising

  # ===================================================================
  # multi-tool sequence  (biggest gap: ZERO coverage anywhere)
  # ===================================================================

  @L4 @sequence @routing
  Scenario: the four tools in one chat carry the same session identity
    # The wire half of persistence — honest at L4 (assert session keys match).
    When bash_tool, create_file, view, and str_replace are called in one chat
    Then all four exec hops carry the same session identity in order
    # does NOT prove the filesystem persisted — that is the L5 scenario below

  @L5 @sequence @persistence
  Scenario: a later call sees the workspace a earlier call wrote
    # The riskiest single property. Provable NOW with /bin/sh alone (no #122):
    # if control recreates the container per exec, call 2 sees no file -> red.
    Given one chat session
    When bash_tool writes a marker file to the workspace
    And a later bash_tool call reads that same path
    Then the second call sees the marker the first call wrote

  @L5 @sequence @full
  Scenario: create then view then edit then confirm over one workspace
    # The full owner-shown journey. Upgrade of the degenerate persistence
    # scenario once the python3 FAT guest is the demo default (#122).
    Given one chat session on a python3-bearing guest
    When create_file writes "ALPHA original" to a file
    And view shows that file
    And str_replace edits "original" to "EDITED"
    And bash_tool cats the file
    Then the final output contains "ALPHA EDITED"
    And no tool fell back to bash for a file operation
