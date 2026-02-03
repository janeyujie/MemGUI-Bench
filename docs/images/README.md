# Images for MemGUI-Bench Project Page

Please add the following images from your paper to this folder:

## Required Images

| Filename | Source | Description |
|----------|--------|-------------|
| `fig1-overview.png` | Figure 1 | MemGUI-Bench Overview - main teaser figure |
| `fig2-task-suite.png` | Figure 2 | Task Suite Statistics - pie chart and bar chart |
| `fig3-architecture.png` | Figure 3 | Unified Architecture - plug-and-play framework |
| `fig4-eval-pipeline.png` | Figure 4 | MemGUI-Eval Progressive Scrutiny Pipeline |

## Optional Images (for expanded content)

| Filename | Source | Description |
|----------|--------|-------------|
| `stage1-success.png` | Appendix | MemGUI-Eval Stage 1 Success Case |
| `stage2-success.png` | Appendix | MemGUI-Eval Stage 2 Success Case |
| `stage2-failed.png` | Appendix | MemGUI-Eval Stage 2 Failed Case |
| `stage3-success.png` | Appendix | MemGUI-Eval Stage 3 Success Case |
| `stage3-failed.png` | Appendix | MemGUI-Eval Stage 3 Failed Case |

## How to Export from LaTeX

1. Compile your LaTeX document to PDF
2. Use a tool like `pdftoppm` or Adobe Acrobat to extract figures
3. Or export from your source files (DrawIO, etc.)

```bash
# Example: Convert PDF figures to PNG
pdftoppm -png -r 300 images/memgui-eval-case/stage1-success.pdf stage1-success
```

## Recommended Image Settings

- Format: PNG (for diagrams) or JPG (for photos)
- Resolution: 300 DPI minimum
- Width: At least 1200px for full-width figures
- Optimize for web using tools like `pngquant` or `optipng`

