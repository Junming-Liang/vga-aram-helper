# VGA 乱斗助手应用图标

本目录为项目新制作的 VGA 字母应用图标。采用金色金属、深蓝底和青色魔法科技光效的原创组合。没有使用或临摹 Riot Games、英雄联盟的官方标志、角色或游戏图标；不表示官方授权或关联。

## 文件

- `vga.ico`：Windows 多分辨率图标，包含 16、24、32、48、64、128、256 像素帧。
- `vga-icon-1024.png`、`vga-icon-512.png`：大尺寸展示 / 应用资源。
- `vga-icon-16.png` 至 `vga-icon-256.png`：单独导出的尺寸。
- `vga-icon-source.png`：生成工具输出的原始 1254 × 1254 PNG。

图标为带透明圆角外区域的栅格作品。本次没有人工绘制矢量源，因此不提供伪装为可编辑矢量的 SVG。

## 制作与验证

- 2026-10-12 使用 OpenAI 内置图像生成工具制作。
- 使用 ImageMagick 进行尺寸与 Windows ICO 格式导出，没有改变画面设计。
- 已目视检查 512 px 和 32 px；V、G、A 字母可辨认。
- 已验证 ICO 包含上述七种尺寸。
- 本项目图标与原创代码一样，按仓库 LICENSE 中的 MIT 条款提供，受适用法律和第三方商标权限制。英雄联盟等名称归各自权利人所有。

## 可复现导出

从本目录运行：

```sh
for s in 16 24 32 48 64 128 256 512 1024; do
  magick vga-icon-source.png -filter Lanczos -resize ${s}x${s} vga-icon-${s}.png
done
magick vga-icon-1024.png -define icon:auto-resize=256,128,64,48,32,24,16 vga.ico
```

## 生成提示词

Use case: logo-brand.
Asset type: original Windows desktop app icon for an independent Chinese League of Legends ARAM helper named VGA乱斗助手.
Primary request: a beautiful, premium high-fantasy game launcher icon combining the uppercase Latin letters V, G, A into one bold, unmistakably readable compact monogram. Exact lettering is VGA, spelled V / G / A, each letter fully recognizable. Use the polished gold-metal, sculpted bevel, deep navy and teal magical-tech visual language associated with premium fantasy strategy game icons, while making an entirely original mark, not a reproduction of any Riot or League of Legends logo.
Composition: square 1024x1024 app icon; a dark midnight-blue rounded-square tile occupying 90% of canvas with subtly chamfered corners; large centralized integrated VGA lettering occupying 78% of tile width and 60% of tile height; visually continuous angular letter geometry with shared diagonal cuts, three letters arranged left to right. Restrained angular gold frame and one small teal rune-like accent above or below the monogram. Letter strokes thick and very high contrast, negative spaces open enough to read at 32 pixels. Avoid clutter, tiny ornament, overly interwoven illegible initials, swords, characters, crowns, animals, or scenery.
Materials: warm antique gold and bright champagne-gold bevel highlights, darker bronze sidewalls, fine crafted metal, subtle cyan/teal inner rim light against dark navy enamel. Flat front view, clean silhouette, no perspective tilt. Beautiful crisp professional icon rendering, elegant controlled light. Transparent pixels outside the rounded-square tile. No text other than VGA, no subtitle, watermark, official logos or simulated UI.
