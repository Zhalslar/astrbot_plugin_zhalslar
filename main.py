import asyncio
import os
from astrbot.api.event import filter
from astrbot.api.star import Context, Star
from astrbot.core.config.astrbot_config import AstrBotConfig
from astrbot.core.platform.astr_message_event import AstrMessageEvent
from astrbot.api import logger


class ZhalslarBundlePlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.context = context
        self.auto_install = self.config.get("auto_install_on_startup", True)
        self.only_admin = self.config.get("only_admin", True)
        self.bundle_plugins = self.config.get("bundle_plugins", [])

        if self.auto_install:
            asyncio.create_task(self._startup_install())

    async def _startup_install(self):
        await asyncio.sleep(5)  # 等待 AstrBot 初始化完成
        logger.info("[ZhalslarBundle] 正在检查并自动安装缺失的捆绑插件...")
        await self._install_missing_plugins()

    def _get_installed_repo_urls(self) -> set[str]:
        installed_urls = set()
        pm = getattr(self.context, "_star_manager", None)
        if not pm:
            return installed_urls

        for star in pm.stars:
            repo = getattr(star, "repo", None)
            if repo:
                clean = repo.strip().rstrip("/").lower()
                installed_urls.add(clean)
                name = clean.split("/")[-1]
                installed_urls.add(name)
        return installed_urls

    async def _install_missing_plugins(self, event: AstrMessageEvent = None):
        pm = getattr(self.context, "_star_manager", None)
        if not pm:
            msg = "[ZhalslarBundle] 无法获取 AstrBot 插件管理器实例。"
            logger.error(msg)
            if event:
                yield event.plain_result(msg)
            return

        installed = self._get_installed_repo_urls()
        to_install = []
        for url in self.bundle_plugins:
            clean = url.strip().rstrip("/").lower()
            name = clean.split("/")[-1]
            if clean not in installed and name not in installed:
                to_install.append(url.strip())

        if not to_install:
            msg = "所有捆绑插件均已安装完毕！"
            logger.info(f"[ZhalslarBundle] {msg}")
            if event:
                yield event.plain_result(msg)
            return

        total = len(to_install)
        if event:
            yield event.plain_result(f"检测到 {total} 个待安装插件，开始自动安装，请稍候...")

        success_count = 0
        fail_count = 0
        for idx, repo_url in enumerate(to_install, 1):
            logger.info(f"[ZhalslarBundle] 正在安装 ({idx}/{total}): {repo_url}")
            try:
                await pm.install_plugin(repo_url=repo_url)
                success_count += 1
            except Exception as e:
                logger.error(f"[ZhalslarBundle] 安装插件失败 {repo_url}: {e}")
                fail_count += 1
            await asyncio.sleep(1)

        result_msg = f"捆绑插件安装完成！\n成功: {success_count} 个\n失败: {fail_count} 个"
        logger.info(f"[ZhalslarBundle] {result_msg}")
        if event:
            yield event.plain_result(result_msg)

    @filter.command_group("zhalslar")
    def zhalslar_group(self):
        pass

    @zhalslar_group.command("install")
    async def install_cmd(self, event: AstrMessageEvent):
        """一键安装/更新所有捆绑插件"""
        if self.only_admin and not event.is_admin():
            yield event.plain_result("只有管理员可以使用该指令。")
            return
        async for res in self._install_missing_plugins(event):
            yield res

    @zhalslar_group.command("list")
    async def list_cmd(self, event: AstrMessageEvent):
        """查看捆绑插件列表"""
        if self.only_admin and not event.is_admin():
            yield event.plain_result("只有管理员可以使用该指令。")
            return
        installed = self._get_installed_repo_urls()
        lines = ["=== Zhalslar 捆绑插件列表 ==="]
        for url in self.bundle_plugins:
            clean = url.strip().rstrip("/").lower()
            name = clean.split("/")[-1]
            status = "已安装" if (clean in installed or name in installed) else "未安装"
            lines.append(f"- [{status}] {name}")
        yield event.plain_result("\n".join(lines))
