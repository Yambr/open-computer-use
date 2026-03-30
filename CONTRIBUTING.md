# Contributing to Open Computer Use

Thank you for your interest! PRs and issues welcome.

## Getting Started

1. Fork the repository
2. Clone: `git clone https://github.com/your-username/openwebui-computer-use-community.git`
3. Branch: `git checkout -b feature/your-feature`

## Development

```bash
cp .env.example .env
# Edit .env with your API key

# Build sandbox image
docker build --platform linux/amd64 -t open-computer-use:latest .

# Run tests
./tests/test-no-corporate.sh
./tests/test-project-structure.sh
./tests/test-docker-image.sh open-computer-use:latest

# Run full stack
docker compose up --build
```

## Testing

Before submitting a PR, all tests must pass:

```bash
./tests/test-no-corporate.sh       # No corporate references
./tests/test-project-structure.sh   # Correct directory structure
./tests/test-docker-image.sh        # Docker image validation
```

## Pull Request Process

1. All tests pass
2. Documentation updated if needed
3. Clear PR description
4. Reference related issues

## Creating Skills

1. Create a directory under `skills/public/` or `skills/examples/`
2. Include `SKILL.md` with name, description, usage examples
3. Put scripts in `scripts/` subdirectory

See [docs/DYNAMIC-SKILLS.md](docs/DYNAMIC-SKILLS.md) for the skill format.

## License

By contributing, you agree your contributions will be licensed under the MIT License.
