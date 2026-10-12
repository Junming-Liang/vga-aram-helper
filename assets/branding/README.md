# VGA 应用图标

项目图标以 VGA 字母、金色金属和深蓝青色底纹组成，用于应用窗口、EXE 和项目展示。图标不含 Riot Games、英雄联盟官方标志或角色素材，不表示官方关联。

## 文件

- `vga.ico`：包含 16、24、32、48、64、128、256 像素的 Windows 多分辨率图标。
- `vga-icon-16.png` 至 `vga-icon-1024.png`：各尺寸 PNG。
- `vga-icon-source.png`：1254 × 1254 原始 PNG，圆角外区域透明。

图标于 2026-10-12 使用 OpenAI 图像生成工具制作，再用 ImageMagick 导出各尺寸和 ICO。源文件为栅格图，没有矢量版本。已检查 512 px、32 px 显示效果及 ICO 内的七种尺寸。

图标按仓库 [MIT License](../../LICENSE) 提供；相关游戏名称和第三方商标仍归各自权利人所有。

## 导出

在本目录运行：

```sh
for s in 16 24 32 48 64 128 256 512 1024; do
  magick vga-icon-source.png -filter Lanczos -resize ${s}x${s} vga-icon-${s}.png
done
magick vga-icon-1024.png -define icon:auto-resize=256,128,64,48,32,24,16 vga.ico
```
