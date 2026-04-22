import aiohttp
import asyncio
import os
import tempfile
import time
import re
from pathlib import Path
from typing import Dict, List, Optional

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from astrbot.api.message_components import Plain, Node, Nodes

API_BASE_URL = "https://jinhong270-api.hf.space"

@register("astrbot_Jinhong270_bilibili", "Jinhong270", "B站视频搜索下载一体化插件", "1.1.0")
class Jinhong270BilibiliPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        config = context.get_config() or {}
        self.temp_retention = config.get("temp_file_retention", 3600)
        self.max_search_results = config.get("max_search_results", 10)
        self.download_timeout = config.get("download_timeout", 120)
        self.user_sessions: Dict[str, dict] = {}
        self.temp_dir = Path(tempfile.gettempdir()) / "astrbot_bilibili_cache"
        self.temp_dir.mkdir(exist_ok=True)
        asyncio.create_task(self._clean_temp_files_loop())

    async def _clean_temp_files_loop(self):
        while True:
            try:
                now = time.time()
                for f in self.temp_dir.iterdir():
                    if f.is_file() and (now - f.stat().st_mtime) > self.temp_retention:
                        f.unlink(missing_ok=True)
            except Exception:
                pass
            await asyncio.sleep(600)

    @filter.regex(r"^/bilibili\s+help$")
    async def bilibili_help(self, event: AstrMessageEvent):
        yield event.plain_result("📺 Bilibili 插件帮助\n发送 search 关键词 或直接发送 search 开始搜索下载。")

    async def _fetch_api(self, endpoint: str, params: dict = None) -> dict:
        url = f"{API_BASE_URL}{endpoint}"
        timeout = aiohttp.ClientTimeout(total=30)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, params=params) as resp:
                    resp.raise_for_status()
                    return await resp.json()
        except Exception as e:
            logger.error(f"API请求失败: {e}")
            return {"error": str(e)}

    async def _download_file(self, url: str, save_path: Path) -> bool:
        timeout = aiohttp.ClientTimeout(total=self.download_timeout)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url) as resp:
                    resp.raise_for_status()
                    with open(save_path, 'wb') as f:
                        async for chunk in resp.content.iter_chunked(8192):
                            f.write(chunk)
            return True
        except Exception as e:
            logger.error(f"下载失败: {e}")
            return False

    def _parse_bvid(self, text: str) -> Optional[str]:
        patterns = [
            r'(BV[a-zA-Z0-9]{10})',
            r'bvid=([a-zA-Z0-9]{12})',
            r'video/(BV[a-zA-Z0-9]{10})',
        ]
        for p in patterns:
            m = re.search(p, text)
            if m:
                return m.group(1)
        return None

    def _format_video_info(self, data: dict) -> str:
        if not data:
            return "获取信息失败"
        title = data.get("title", "未知")
        bvid = data.get("bvid", "未知")
        owner = data.get("owner", {}).get("name", "未知")
        stat = data.get("stat", {})
        view = stat.get("view", "0")
        like = stat.get("like", "0")
        coin = stat.get("coin", "0")
        favorite = stat.get("favorite", "0")
        share = stat.get("share", "0")
        danmaku = stat.get("danmaku", "0")
        pubdate = data.get("pubdate", 0)
        pubdate_str = time.strftime("%Y-%m-%d", time.localtime(pubdate)) if pubdate else "未知"
        desc = data.get("desc", "")
        if len(desc) > 200:
            desc = desc[:200] + "..."
        return f"📹 {title}\n🔗 {bvid}\n👤 {owner}\n📅 {pubdate_str}\n▶️ 播放:{view} 👍{like} 💰{coin} ⭐{favorite} 🔁{share} 💬{danmaku}\n📝 {desc}"

    @filter.command("search")
    async def search_entry(self, event: AstrMessageEvent):
        msg = event.message_str.strip()
        if msg == "search":
            self.user_sessions[event.unified_msg_origin] = {"state": "awaiting_keyword"}
            yield event.plain_result("告诉我你的关键词吧～")
            return
        parts = msg.split(maxsplit=1)
        if len(parts) < 2:
            yield event.plain_result("格式：search 关键词")
            return
        keyword = parts[1].strip()
        async for result in self._do_search(event, keyword):
            yield result

    async def _do_search(self, event: AstrMessageEvent, keyword: str):
        data = await self._fetch_api(f"/bilibili/search/{keyword}", params={"page": 1, "page_size": self.max_search_results})
        if "error" in data:
            yield event.plain_result(f"搜索失败: {data['error']}")
            return
        videos = []
        if isinstance(data, dict):
            videos = data.get("data", {}).get("result", [])
        elif isinstance(data, list):
            videos = data
        if not videos:
            yield event.plain_result(f"未找到关于 '{keyword}' 的视频。")
            return
        nodes = []
        for idx, v in enumerate(videos[:self.max_search_results], 1):
            title = v.get("title", "").replace("<em class=\"keyword\">", "").replace("</em>", "")
            bvid = v.get("bvid", "")
            author = v.get("author", v.get("owner", {}).get("name", "未知"))
            duration = v.get("duration", "未知")
            play = v.get("play", v.get("stat", {}).get("view", "0"))
            content = f"{idx}. {title}\nBV:{bvid} | UP:{author}\n时长:{duration} | 播放:{play}"
            nodes.append(Node(content=[Plain(content)]))
        try:
            yield event.chain_result([Nodes(nodes)])
        except Exception:
            text_result = "\n".join([n.content[0].text for n in nodes])
            yield event.plain_result(text_result)
        self.user_sessions[event.unified_msg_origin] = {
            "state": "awaiting_selection",
            "videos": videos[:self.max_search_results]
        }

    @filter.regex(r'^(?!search\b).*')
    async def handle_user_reply(self, event: AstrMessageEvent):
        session_key = event.unified_msg_origin
        if session_key not in self.user_sessions:
            return
        session = self.user_sessions[session_key]
        msg = event.message_str.strip()
        if session["state"] == "awaiting_keyword":
            del self.user_sessions[session_key]
            async for result in self._do_search(event, msg):
                yield result
        elif session["state"] == "awaiting_selection":
            videos = session.get("videos", [])
            del self.user_sessions[session_key]
            try:
                idx = int(msg) - 1
                if idx < 0 or idx >= len(videos):
                    yield event.plain_result("序号无效，请重新搜索。")
                    return
                video = videos[idx]
                bvid = video.get("bvid")
                if not bvid:
                    yield event.plain_result("无法获取BV号。")
                    return
            except ValueError:
                yield event.plain_result("请输入有效数字序号。")
                return
            info_data = await self._fetch_api(f"/bilibili/video/{bvid}")
            if "error" in info_data:
                yield event.plain_result(f"获取视频信息失败: {info_data['error']}")
                return
            info_text = self._format_video_info(info_data)
            yield event.plain_result(info_text)
            download_data = await self._fetch_api(f"/bilibili/video/download/{bvid}")
            if "error" in download_data:
                yield event.plain_result(f"获取下载链接失败: {download_data['error']}")
                return
            download_url = download_data.get("url")
            if not download_url:
                yield event.plain_result("下载链接为空。")
                return
            yield event.plain_result("正在下载视频，请稍候...")
            video_title = info_data.get("title", video.get("title", "video"))
            safe_title = re.sub(r'[\\/*?:"<>|]', "", video_title)[:50]
            file_path = self.temp_dir / f"{safe_title}.mp4"
            success = await self._download_file(download_url, file_path)
            if not success or not file_path.exists():
                yield event.plain_result("视频下载失败。")
                return
            try:
                yield event.file_result(str(file_path))
            except Exception as e:
                yield event.plain_result(f"发送文件失败: {e}\n下载链接: {download_url}")

    async def terminate(self):
        logger.info("Jinhong270 Bilibili 插件已停止。")