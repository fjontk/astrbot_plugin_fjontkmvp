from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api.provider import ProviderRequest
from astrbot.api import AstrBotConfig, logger
from .service import InjectionService

@register("prompt_injector", "fjontk", "一个暴力但轻量的提示词注入插件", "1.1.0")
class PromptInjector(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.service = InjectionService(self, config)

    @filter.command("set_task")
    async def set_task(self, event: AstrMessageEvent):
        """设置当前任务提示词。用法: /set_task [轮次] <内容>"""
        async for r in self._handle_set_command(event, "task", "当前任务"):
            yield r

    @filter.command("set_know")
    async def set_know(self, event: AstrMessageEvent):
        """设置附加知识提示词。用法: /set_know [轮次] <内容>"""
        async for r in self._handle_set_command(event, "knowledge", "附加知识"):
            yield r

    async def _handle_set_command(self, event: AstrMessageEvent, type_name: str, display_name: str):
        if not self.service.check_whitelist(event):
            yield event.plain_result(f"❌ 当前会话不在白名单中，无法使用注入功能。")
            return

        msg_str = event.message_str.strip()
        parts = msg_str.split(maxsplit=2)
        
        if len(parts) < 2:
             cmd = event.message_obj.raw_message.split()[0]
             yield event.plain_result(f"❌ 请输入内容。用法: /{cmd} [轮次] <内容>")
             return
        
        default_turns = self.config.get("default_turns", 10)
        max_turns = self.config.get("max_turns_limit", 50)
        current_turns = default_turns
        content = ""
        
        try:
            potential_turns = int(parts[1])
            if len(parts) > 2:
                current_turns = potential_turns
                content = parts[2]
            else:
                content = parts[1] 
        except ValueError:
            # Check for suffixes like " content 20"
            import re
            match = re.search(r'^(.*)\s+(\d+)$', msg_str.split(maxsplit=1)[1])
            if match:
                 content = match.group(1)
                 current_turns = int(match.group(2))
            else:
                 content = msg_str.split(maxsplit=1)[1]

        if current_turns > max_turns:
            current_turns = max_turns
            yield event.plain_result(f"⚠️ 设置的轮次超过上限，已自动调整为 {max_turns} 轮。")

        success, msg = await self.service.add_injection(event, type_name, content, current_turns)
        if not success:
            yield event.plain_result(msg)
        else:
            yield event.plain_result(f"✅ {display_name}已注入，将在 {current_turns} 轮对话内生效。")



    @filter.command("show_injections")
    async def show_injections(self, event: AstrMessageEvent):
        """查看当前生效的注入信息"""
        injections = await self.service.get_injections(event)
        
        if not injections:
            yield event.plain_result("📭 当前会话没有生效的注入信息。")
            return

        msg = ["📋 当前注入信息："]
        for idx, item in enumerate(injections):
            t = "📌 任务" if item["type"] == "task" else "📚 知识"
            c = item['content']
            display_content = c[:20] + "..." if len(c) > 20 else c
            msg.append(f"{idx+1}. {t} (剩 {item['turns_left']} 轮): {display_content}")
            
        yield event.plain_result("\n".join(msg))

    @filter.command("clear_injections")
    async def clear_injections(self, event: AstrMessageEvent):
        """清除当前所有注入"""
        await self.service.clear_injections(event)
        yield event.plain_result("🗑️ 已清除所有注入信息。")

    @filter.command("add_whitelist")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def add_whitelist(self, event: AstrMessageEvent):
        """(管理员) 将当前会话加入白名单"""
        whitelist = self.config.get("whitelist", [])
        sid = event.unified_msg_origin
        if sid not in whitelist:
            whitelist.append(sid)
            self.config["whitelist"] = whitelist
            self.config.save_config()
            yield event.plain_result(f"✅ 已将会话 {sid} 加入白名单。")
        else:
            yield event.plain_result("⚠️ 该会话已在白名单中。")

    @filter.on_llm_request()
    async def inject_prompts(self, event: AstrMessageEvent, req: ProviderRequest):
        """在 LLM 请求前注入提示词"""
        if not self.service.check_whitelist(event):
            return

        injection_text = await self.service.get_formatted_injection_text(event)
        
        if injection_text:
            if req.system_prompt:
                # Prepend the injection text to the system prompt
                req.system_prompt = injection_text + req.system_prompt
            else:
                req.system_prompt = injection_text
            
            logger.info(f"Injected prompt for {event.unified_msg_origin}.")
