# 在 GitHub Actions 中下载并提交 XYZ 瓦片

本工程可以通过 GitHub Actions 将**有权离线保存和公开分发**的 XYZ 地图瓦片写入 GitHub 仓库。需要先确认地图数据提供方的存储、批量请求和再发布许可。

## 一键运行

进入 [Actions → Download authorized tiles into repository](../actions/workflows/download-tiles-to-repo.yml) → **Run workflow**，填写：

| 参数 | 说明 | 默认值 |
| --- | --- | --- |
| `bbox` | 经纬度范围：最小经度,最小纬度,最大经度,最大纬度 | `113.93,22.58,114.25,22.77`（深圳局部示例） |
| `min_zoom` / `max_zoom` | XYZ 缩放层级 | `6` / `8` |
| `tile_url` | 确认授权的 HTTPS XYZ 模板，必须包含 `{z}`、`{y}`、`{x}` | NASA GIBS Blue Marble |
| `extension` | 图片后缀与实际编码一致 | `jpeg` |
| `dataset` | 子目录标识 | `nasa-blue-marble` |
| `max_tiles` | 单次下载保护上限（1~500） | `200` |

Actions 运行完成后会执行 `git add tiles/` → `git commit` → `git push origin main`，生成：

```text
tiles/
└── nasa-blue-marble/
    ├── 6/
    │   └── 27/
    │       └── 52.jpeg
    ├── 7/
    ├── 8/
    └── source.json
```

瓦片按 `tiles/<dataset>/<z>/<y>/<x>.<ext>` 保存，符合 XYZ 标准，可由 Leaflet/OpenLayers 等地图组件读取。下载器会校验 PNG/JPEG/WebP 文件头，遇到无效内容直接失败，已经存在的有效瓦片会跳过。

## 地图源许可

默认示例为 **NASA Global Imagery Browse Services（GIBS）Blue Marble** 的开放卫星影像，范围是深圳附近，等级 6~8，主要用于验证实际瓦片能够从网络下载并写入仓库。来源：https://gibs.earthdata.nasa.gov ，图像致谢：

> Imagery provided by services from NASA's Global Imagery Browse Services (GIBS), part of NASA's Earth Science Data and Information System (ESDIS).

**高德地图瓦片不得未经许可批量抓取、缓存并再公开传播。** 官方条款参见 https://developer.amap.com/pages/terms/ 。如要用高德等商业地图源，请先取得明确的离线存储与转授权许可，再手动替换工作流中的源地址与版权声明。

## 注意

- GitHub 仓库用于放置**小规模、合法可分发**的地图数据。大量瓦片应存到对象存储或离线文件服务器。
- GitHub 官方推荐单个仓库 Git 对象保持在 10 GB 以内（建议阈值，非硬性配额）。参考：https://docs.github.com/en/repositories/creating-and-managing-repositories/repository-limits
- NASA 演示地图的最大层级为 8；如需更高层级，须改用允许对应层级并允许离线保存的源。
- 仅下载真实图片文件到仓库，`source.json` 保存来源、范围和坐标系信息，**不会保存自定义源中可能包含的密钥**。
- Actions 运行成功后，瓦片提交记录会显示为 `github-actions[bot]`。
