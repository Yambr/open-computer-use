# Skills System Documentation

Guide to the AI Computer Use Skills System.

## Overview

The Skills system provides enhanced capabilities for AI assistants through pre-packaged tools, scripts, and documentation. Skills are organized into categories and mounted read-only in the container.

## Directory Structure

```
skills/
├── public/              # Core production-ready skills
│   ├── docx/           # Word document processing
│   ├── pdf/            # PDF operations
│   ├── pptx/           # PowerPoint presentations
│   ├── xlsx/           # Excel spreadsheets
│   ├── skill-creator/  # Create new skills
│   ├── sub-agent/      # Task delegation to autonomous agent
│   └── product-self-knowledge/
│
└── examples/           # Example implementations
    ├── mcp-builder/    # Build MCP servers
    ├── canvas-design/  # Design in Canvas
    ├── algorithmic-art/
    ├── theme-factory/
    └── ... (10+ examples)
```

## Public Skills

### 1. docx - Word Documents

**Location**: `/mnt/skills/public/docx/`

**Capabilities**:
- Create and edit .docx files
- Work with styles, tables, images
- OOXML schema validation
- Comment tracking

**Key Files**:
- `SKILL.md` - Usage guide
- `docx-js.md` - JavaScript library docs
- `ooxml/schemas/` - ISO 29500 XSD schemas
- `scripts/document.py` - Python utilities

**Example**:
```python
from docx import Document

doc = Document()
doc.add_heading('Report', 0)
doc.add_paragraph('Content here...')
doc.save('/mnt/user-data/outputs/report.docx')
```

### 2. pdf - PDF Processing

**Location**: `/mnt/skills/public/pdf/`

**Capabilities**:
- Extract text and images
- Fill PDF forms
- Create validation images
- Check bounding boxes

**Key Files**:
- `SKILL.md` - Main guide
- `FORMS.md` - Form filling guide
- `REFERENCE.md` - API reference
- `scripts/` - 8 Python scripts for PDF operations

**Example**:
```bash
# Fill PDF form
python3 /mnt/skills/public/pdf/scripts/fill_pdf_form_with_annotations.py \
  /mnt/user-data/uploads/form.pdf \
  /mnt/user-data/outputs/filled.pdf
```

### 3. pptx - PowerPoint Presentations

**Location**: `/mnt/skills/public/pptx/`

**Capabilities**:
- Create presentations programmatically
- Convert HTML to PowerPoint
- Manipulate slides, layouts, themes
- Extract thumbnails

**Key Files**:
- `SKILL.md` - Usage guide
- `html2pptx.md` - HTML conversion guide
- `css.md` - Styling guide
- `html2pptx.tgz` - npm package for HTML→PPTX
- `scripts/` - Python utilities

**Example**:
```python
from pptx import Presentation

prs = Presentation()
slide = prs.slides.add_slide(prs.slide_layouts[0])
title = slide.shapes.title
title.text = "My Presentation"
prs.save('/mnt/user-data/outputs/presentation.pptx')
```

### 4. xlsx - Excel Spreadsheets

**Location**: `/mnt/skills/public/xlsx/`

**Capabilities**:
- Read and write .xlsx files
- Formulas, formatting, charts
- Multiple worksheets
- Data validation

**Example**:
```python
from openpyxl import Workbook

wb = Workbook()
ws = wb.active
ws['A1'] = 'Hello'
ws['B1'] = 123
wb.save('/mnt/user-data/outputs/data.xlsx')
```

### 5. skill-creator - Create New Skills

**Location**: `/mnt/skills/public/skill-creator/`

**Purpose**: Template and tools for creating custom skills

**Key Files**:
- `SKILL.md` - Creation guide
- `references/workflows.md` - Workflow patterns
- `references/output-patterns.md` - Output formatting
- `scripts/init_skill.py` - Initialize new skill
- `scripts/package_skill.py` - Package for distribution

### 6. product-self-knowledge

**Location**: `/mnt/skills/public/product-self-knowledge/`

**Purpose**: AI assistant's knowledge about its own capabilities and features

### 7. sub-agent - Task Delegation

**Location**: `/mnt/skills/public/sub-agent/`

**Purpose**: Delegate complex, multi-step tasks to autonomous Claude agent

**Capabilities**:
- Creating presentations (10+ slides)
- Multi-file refactoring
- Iterative test-fix cycles
- Research and reports
- Code review with fixes
- Complex Git operations

**Key Files**:
- `SKILL.md` - Main documentation
- `references/usage.md` - Task templates and patterns
- `references/security-review.md` - Security review template

**When to use:**
- Tasks requiring 10+ tool calls
- Iterative workflows (test → fix → repeat)
- Tasks requiring autonomous reasoning
- Complex document creation

**When NOT to use:**
- Simple file reads/writes
- Single bash commands
- Quick edits to one file

**Example**:
```python
sub_agent(
    task="""
## ROLE
You are a business presentation specialist.

## DIRECTIVE
Create a 12-slide presentation on AI trends.

## CONSTRAINTS
- Do NOT use technical jargon
- Do NOT include more than 5 bullets per slide

## PROCESS
1. Research current AI adoption statistics
2. Create slide outline
3. Build presentation with charts
4. Add speaker notes

## OUTPUT
- Save to /mnt/user-data/outputs/ai_trends.pptx
""",
    description="AI presentation for board meeting",
    max_turns=50
)
```

## Example Skills

### mcp-builder - MCP Server Builder

**Location**: `/mnt/skills/examples/mcp-builder/`

**Purpose**: Build high-quality MCP (Model Context Protocol) servers

**Key Files**:
- `SKILL.md` - Complete guide (329 lines)
- `reference/python_mcp_server.md` - Python/FastMCP guide
- `reference/node_mcp_server.md` - TypeScript/Node guide
- `reference/mcp_best_practices.md` - Best practices
- `reference/evaluation.md` - Testing guide
- `scripts/connections.py` - Connection management
- `scripts/evaluation.py` - Run evaluations

**Features**:
- FastMCP (Python) support
- TypeScript/Node MCP SDK support
- Pydantic/Zod validation
- Evaluation-driven development
- 4-phase workflow (Research → Implement → Review → Test)

**Example Usage**:
See [scripts/mcp-server/](../scripts/mcp-server/) for a working example built with this skill.

### canvas-design - Design in Canvas

**Location**: `/mnt/skills/examples/canvas-design/`

**Features**:
- 90+ TTF fonts included
- Font families: RedHatMono, JetBrainsMono, Lora, Outfit, etc.
- Ready for Canvas artifact creation

### algorithmic-art - Generative Art

**Location**: `/mnt/skills/examples/algorithmic-art/`

**Features**:
- HTML viewer template
- JavaScript generator template
- Create interactive visualizations

### theme-factory - Design Themes

**Location**: `/mnt/skills/examples/theme-factory/`

**Features**:
- 10 pre-built themes (arctic-frost, ocean-depths, midnight-galaxy, etc.)
- Color palettes
- Typography systems
- Theme showcase PDF

### Other Example Skills

- **artifacts-builder**: Create React artifacts with shadcn components
- **internal-comms**: Internal communication templates
- **single-cell-rna-qc**: Bioinformatics RNA quality control
- **slack-gif-creator**: Generate GIFs for Slack
- **brand-guidelines**: Branding and style guides

## Using Skills

### From Container

```bash
# Access container
docker-compose exec ai-computer-use /bin/bash

# List available skills
ls /mnt/skills/public/
ls /mnt/skills/examples/

# Read skill documentation
cat /mnt/skills/public/docx/SKILL.md

# Use skill script
python3 /mnt/skills/public/pdf/scripts/extract_form_field_info.py \
  /mnt/user-data/uploads/form.pdf
```

### From Host (via MCP)

If you have the MCP server set up:

```
You: "Use the PDF skill to extract form fields from uploaded form.pdf"
Assistant: [Executes via MCP server]
```

## Creating Custom Skills

### 1. Use skill-creator

```bash
cd /mnt/skills/public/skill-creator/scripts
python3 init_skill.py --name my-skill --type public
```

### 2. Structure

```
my-skill/
├── SKILL.md         # Documentation
├── LICENSE.txt      # License
├── reference/       # Additional docs
│   └── guide.md
├── scripts/         # Python/bash scripts
│   └── tool.py
└── examples/        # Usage examples
    └── example1.md
```

### 3. Best Practices

1. **Clear Documentation**: Comprehensive SKILL.md
2. **Self-contained**: All dependencies listed
3. **Examples**: Provide working examples
4. **Error Handling**: Graceful failure messages
5. **Testing**: Include test cases

### 4. Packaging

```bash
cd /mnt/skills/public/skill-creator/scripts
python3 package_skill.py --input /path/to/my-skill
```

## Skill Development Workflow

### Phase 1: Research
- Understand the API/domain
- Review existing skills
- Identify core functionality

### Phase 2: Implementation
- Create skill structure
- Write scripts and utilities
- Add documentation

### Phase 3: Testing
- Test on real data
- Verify error handling
- Check edge cases

### Phase 4: Documentation
- Complete SKILL.md
- Add examples
- Document limitations

## OOXML Support

Both docx and pptx skills include full OOXML schema support:

**Schemas Included**:
- ISO/IEC 29500-4:2016 (Office Open XML)
- ECMA-376 4th Edition
- Microsoft extensions (2010, 2012, 2018)

**Location**: `/mnt/skills/public/{docx,pptx}/ooxml/schemas/`

**Validation Scripts**:
```bash
# Validate DOCX
python3 /mnt/skills/public/docx/ooxml/scripts/validate.py document.docx

# Unpack for inspection
python3 /mnt/skills/public/docx/ooxml/scripts/unpack.py document.docx output_dir/

# Pack after modification
python3 /mnt/skills/public/docx/ooxml/scripts/pack.py input_dir/ output.docx
```

## Font Support

### System Fonts (in container)

- Liberation (Serif, Sans, Mono)
- DejaVu (Serif, Sans, Mono)
- Noto CJK (Chinese, Japanese, Korean)
- Noto Color Emoji

### Canvas Fonts (in skills)

Location: `/mnt/skills/examples/canvas-design/canvas-fonts/`

90+ TTF files including:
- Monospace: JetBrainsMono, RedHatMono, GeistMono, DMMono
- Serif: Lora, LibreBaskerville, CrimsonPro, YoungSerif
- Sans: Outfit, WorkSans, InstrumentSans
- Display: Gloock, EricaOne, Italiana, PoiretOne

## Troubleshooting

### Skill Not Found

```bash
# Verify mount
docker-compose exec ai-computer-use ls /mnt/skills/

# Check docker-compose.yml
grep -A2 "skills:" docker-compose.yml
```

### Script Execution Fails

```bash
# Check permissions
docker-compose exec ai-computer-use ls -la /mnt/skills/public/pdf/scripts/

# Verify Python packages
docker-compose exec ai-computer-use python3 -c "import pypdf; print('OK')"
```

### Missing Dependencies

```bash
# Install additional Python package
docker-compose exec ai-computer-use pip install package-name

# Or add to requirements.txt and rebuild
echo "package-name==version" >> requirements.txt
docker-compose build --no-cache
```

## Best Practices

### 1. Read-Only Skills
Skills are mounted read-only. For modifications:
- Copy to `/home/claude/` (ephemeral workspace)
- Or write outputs to `/mnt/user-data/outputs/`

### 2. File Paths
Always use absolute paths:
```python
# Good
script = "/mnt/skills/public/pdf/scripts/tool.py"

# Bad (relative paths may not work)
script = "../skills/public/pdf/scripts/tool.py"
```

### 3. Error Handling
Skills should handle errors gracefully:
```python
try:
    process_document(input_file)
except FileNotFoundError:
    print(f"Error: File not found: {input_file}")
    sys.exit(1)
```

### 4. Documentation
Always check SKILL.md first:
```bash
cat /mnt/skills/public/docx/SKILL.md | less
```

## Contributing

To contribute new skills or improvements:

1. Follow the skill-creator guidelines
2. Test thoroughly in container
3. Document all functionality
4. Package with `package_skill.py`
5. Submit for review

## References

- [MCP Best Practices](/mnt/skills/examples/mcp-builder/reference/mcp_best_practices.md)
- [Output Patterns](/mnt/skills/public/skill-creator/references/output-patterns.md)
- [Workflow Guide](/mnt/skills/public/skill-creator/references/workflows.md)

## Support

For skill-related issues:
1. Check SKILL.md in the skill directory
2. Review example usage
3. Verify container has required packages
4. Test script directly in container
