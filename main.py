import aiohttp
import aiofiles
import asyncio
import tempfile
import time
import re
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import quote

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger

@register("astrbot_Jinhong270_bilibili", "Jinhong270", "B站视频搜索下载一体化插件", "1.1.0")
class Jinhong270BilibiliPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        config = context.get_config() or {}
        self.api_base_url = "https://jinhong270-api.hf.space"
        self.temp_retention = config.get("temp_file_retention", 3600)
        self.max_search_results = config.get("max_search_results", 10)
        self.download_timeout = config.get("download_timeout", 120)
        self.user_sessions: Dict[str, dict] = {}
        self.temp_dir = Path(tempfile.gettempdir()) / "astrbot_bilibili_cache"
        self.temp_dir.mkdir(exist_ok=True)
        self._clean_task = asyncio.create_task(self._clean_temp_files_loop())

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

    async def _fetch_api(self, endpoint: str, params: dict = None) -> dict:
        url = f"{self.api_base_url}{endpoint}"
        timeout = aiohttp.ClientTimeout(total=30)
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://www.bilibili.com"
        }
        try:
            async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
                async with session.get(url, params=params) as resp:
                    resp.raise_for_status()
                    return await resp.json(content_type=None)
        except Exception as e:
            logger.error(f"API请求失败 {endpoint}: {e}")
            return {"error": str(e)}

    async def _download_file(self, url: str, save_path: Path) -> bool:
        timeout = aiohttp.ClientTimeout(total=self.download_timeout)
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://www.bilibili.com",
            "Origin": "https://www.bilibili.com"
        }
        try:
            async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
                async with session.get(url) as resp:
                    resp.raise_for_status()
                    async with aiofiles.open(save_path, 'wb') as f:
                        async for chunk in resp.content.iter_chunked(8192):
                            await f.write(chunk)
            return True
        except Exception as e:
            logger.error(f"下载失败: {e}")
            return False

    def _format_video_info(self, data: dict) -> str:
        if not data:
            return "获取信息失败"
        if "data" in data:
            data = data["data"]
        if "View" in data:
            data = data["View"]
        title = data.get("title") or data.get("Title") or "未知"
        bvid = data.get("bvid") or data.get("Bvid") or "未知"
        owner = data.get("owner", {})
        if isinstance(owner, dict):
            owner_name = owner.get("name") or owner.get("Name") or "未知"
        else:
            owner_name = "未知"
        stat = data.get("stat") or data.get("Stat") or {}
        view = stat.get("view") or stat.get("View") or "0"
        like = stat.get("like") or stat.get("Like") or "0"
        coin = stat.get("coin") or stat.get("Coin") or "0"
        favorite = stat.get("favorite") or stat.get("Favorite") or "0"
        share = stat.get("share") or stat.get("Share") or "0"
        danmaku = stat.get("danmaku") or stat.get("Danmaku") or "0"
        pubdate = data.get("pubdate") or data.get("Pubdate") or data.get("ctime") or data.get("Ctime") or 0
        if pubdate:
            try:
                pubdate_str = time.strftime("%Y-%m-%d", time.localtime(pubdate))
            except:
                pubdate_str = "未知"
        else:
            pubdate_str = "未知"
        desc = data.get("desc") or data.get("Desc") or ""
        if len(desc) > 200:
            desc = desc[:200] + "..."
        return f"📹 {title}\n🔗 {bvid}\n👤 {owner_name}\n📅 {pubdate_str}\n▶️ 播放:{view} 👍{like} 💰{coin} ⭐{favorite} 🔁{share} 💬{danmaku}\n📝 {desc}"

    def _extract_bvid(self, text: str) -> Optional[str]:
        patterns = [
            r'(BV[a-zA-Z0-9]{10})',
            r'bvid=([a-zA-Z0-9]{12})',
            r'video/(BV[a-zA-Z0-9]{10})',
            r'bilibili\.com/video/(BV[a-zA-Z0-9]{10})',
            r'b23\.tv/([a-zA-Z0-9]+)'
        ]
        for p in patterns:
            match = re.search(p, text)
            if match:
                return match.group(1)
        return None

    def _extract_download_url(self, download_data: dict) -> Optional[str]:
        if not isinstance(download_data, dict):
            return None
        data = download_data.get("data")
        if not isinstance(data, dict):
            return None
        dash = data.get("dash")
        if isinstance(dash, dict):
            videos = dash.get("video")
            if isinstance(videos, list) and videos:
                first_video = videos[0]
                if isinstance(first_video, dict):
                    return first_video.get("baseUrl") or first_video.get("base_url")
        return None

    async def _send_file_via_onebot(self, event: AstrMessageEvent, file_path: Path):
        """尝试通过 OneBot 协议上传文件，成功返回 True，失败返回 False"""
        try:
            adapter = event.session.adapter
            msg_obj = event.message_obj
            if msg_obj.message_type == 'private':
                user_id = msg_obj.sender.user_id
                await adapter.call_api('upload_private_file', {
                    'user_id': user_id,
                    'file': str(file_path),
                    'name': file_path.name
                })
                return True
            elif msg_obj.message_type == 'group':
                group_id = msg_obj.group_id
                await adapter.call_api('upload_group_file', {
                    'group_id': group_id,
                    'file': str(file_path),
                    'name': file_path.name
                })
                return True
        except Exception as e:
            logger.warning(f"OneBot 文件上传失败: {e}")
        return False

    async def _process_video_by_bvid(self, event: AstrMessageEvent, bvid: str):
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

        download_url = self._extract_download_url(download_data)
        if not download_url:
            logger.warning(f"下载链接解析失败，原始响应: {download_data}")
            yield event.plain_result("下载链接解析失败，请联系管理员。")
            return

        yield event.plain_result("正在下载视频，请稍候...")
        video_title = "bilibili_video"
        if isinstance(info_data, dict):
            if "data" in info_data:
                video_title = info_data["data"].get("title") or video_title
            elif "title" in info_data:
                video_title = info_data["title"]
        safe_title = re.sub(r'[\\/*?:"<>|]', "", video_title) or "bilibili_video"
        safe_title = safe_title[:50]
        file_path = self.temp_dir / f"{safe_title}.mp4"

        success = await self._download_file(download_url, file_path)
        if not success or not file_path.exists():
            yield event.plain_result("视频下载失败。")
            return

        sent = await self._send_file_via_onebot(event, file_path)
        if not sent:
            yield event.plain_result(f"文件上传失败，可手动复制链接下载:\n{download_url}")

    @filter.regex(r'.*(bilibili\.com|BV[a-zA-Z0-9]{10}|b23\.tv).*')
    async def handle_bilibili_link(self, event: AstrMessageEvent):
        msg = event.message_str.strip()
        bvid = self._extract_bvid(msg)
        if not bvid:
            return
        async for result in self._process_video_by_bvid(event, bvid):
            yield result

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
        encoded_keyword = quote(keyword)
        data = await self._fetch_api(f"/bilibili/search/{encoded_keyword}", params={"page": 1, "page_size": self.max_search_results})
        if "error" in data:
            yield event.plain_result(f"搜索失败: {data['error']}")
            return
        videos = []
        if isinstance(data, dict):
            if "data" in data:
                videos = data["data"].get("result") or data["data"].get("list") or []
            elif "result" in data:
                videos = data["result"]
            elif "list" in data:
                videos = data["list"]
        elif isinstance(data, list):
            videos = data
        if not videos:
            yield event.plain_result(f"未找到关于 '{keyword}' 的视频。")
            return

        result_lines = []
        for idx, v in enumerate(videos[:self.max_search_results], 1):
            title = v.get("title", "").replace("<em class=\"keyword\">", "").replace("</em>", "")
            bvid = v.get("bvid") or v.get("bvid_str") or ""
            author = v.get("author") or v.get("owner", {}).get("name") or "未知"
            duration = v.get("duration") or "未知"
            play = v.get("play") or v.get("stat", {}).get("view") or "0"
            line = f"{idx}. {title}\nBV:{bvid} | UP:{author}\n时长:{duration} | 播放:{play}"
            result_lines.append(line)

        full_result = "\n\n".join(result_lines)
        yield event.plain_result(full_result)
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
            return

        if session["state"] == "awaiting_selection":
            videos = session.get("videos", [])
            try:
                idx = int(msg) - 1
                if idx < 0 or idx >= len(videos):
                    yield event.plain_result("序号无效，请重新输入有效序号：")
                    return
                video = videos[idx]
                bvid = video.get("bvid") or video.get("bvid_str")
                if not bvid:
                    yield event.plain_result("无法获取BV号。")
                    return
            except ValueError:
                yield event.plain_result("请输入有效数字序号：")
                return

            del self.user_sessions[session_key]
            async for result in self._process_video_by_bvid(event, bvid):
                yield result

    async def terminate(self):
        if self._clean_task and not self._clean_task.done():
            self._clean_task.cancel()
        logger.info("Jinhong270 Bilibili 插件已停止。")