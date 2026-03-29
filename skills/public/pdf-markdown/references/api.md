# MinerU API

## Endpoint

```
POST https://api.anthropic.com/mineru/file_parse
```

## Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `files` | required | PDF file |
| `lang_list` | `ch` | OCR language: `ru`, `en`, `ch`, `de`, `fr`, `ja`, `ko` |
| `return_md` | `true` | Return markdown |
| `return_images` | `false` | Extract images |
| `response_format_zip` | `false` | Return as ZIP |

## Response (ZIP)

```
<filename>/
├── <filename>.md
└── images/
    └── <hash>.jpg
```
