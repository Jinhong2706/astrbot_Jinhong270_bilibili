# astrbot_Jinhong270_bilibili

一个为 AstrBot 设计的 Bilibili 视频搜索与下载插件，适配 NapCat 平台。

## 功能

- 通过关键词搜索 B 站视频，返回前 10 条结果（合并转发消息）。
- 支持直接发送 `search 关键词` 或单独 `search` 后引导输入关键词。
- 选择序号后自动获取视频详情并下载视频文件，直接发送到聊天窗口。
- 自动清理过期临时文件，可通过配置项调整保留时间。
- 使用 `/bilibili help` 查看帮助。

## 安装

1. 在 AstrBot 插件市场搜索 `astrbot_Jinhong270_bilibili` 并安装。
2. 或手动克隆本仓库到 AstrBot 的 `addons` 目录。

## 配置

在 AstrBot 插件管理界面或 `data/config/plugins/astrbot_Jinhong270_bilibili.yaml` 中可调整以下参数：

- `temp_file_retention`: 临时视频文件保留时间（秒），默认 `3600`。
- `max_search_results`: 搜索结果返回条数，默认 `10`。
- `download_timeout`: 视频下载超时时间（秒），默认 `120`。

## 使用示例
