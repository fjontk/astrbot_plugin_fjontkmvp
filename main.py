from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api.provider import ProviderRequest
from astrbot.api import AstrBotConfig, logger

@register("prompt_injector", "YourName", "当前任务与附加知识提示词注入插件", "1.0.0")
class PromptInjector(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config

    def _get_storage_key(self, event: AstrMessageEvent) -> str:
        """生成基于会话的存储键"""
        return f"injection_{event.unified_msg_origin}"

    def _check_whitelist(self, event: AstrMessageEvent) -> bool:
        """检查白名单。如果未开启白名单模式，直接通过。"""
        if not self.config.get("whitelist_mode", False):
            return True
        
        whitelist = self.config.get("whitelist", [])
        return event.unified_msg_origin in whitelist or event.get_group_id() in whitelist

    @filter.command("set_task")
    async def set_task(self, event: AstrMessageEvent, task: str):
        """设置当前任务提示词"""
        if not self._check_whitelist(event):
            yield event.plain_result("❌ 当前会话不在白名单中，无法使用注入功能。")
            return

        key = self._get_storage_key(event)
        data = await self.get_kv_data(key, {})
        
        data["task"] = task
        # 每次更新任务，重置生效轮次
        data["turns_left"] = self.config.get("max_turns", 10)
        
        await self.put_kv_data(key, data)
        yield event.plain_result(f"✅ 当前任务已注入，将在接下来的 {data['turns_left']} 轮对话中生效。")

    @filter.command("set_know")
    async def set_know(self, event: AstrMessageEvent, knowledge: str):
        """设置附加知识提示词"""
        if not self._check_whitelist(event):
            yield event.plain_result("❌ 当前会话不在白名单中，无法使用注入功能。")
            return

        key = self._get_storage_key(event)
        data = await self.get_kv_data(key, {})
        
        data["knowledge"] = knowledge
        # 每次更新知识，重置生效轮次
        data["turns_left"] = self.config.get("max_turns", 10)
        
        await self.put_kv_data(key, data)
        yield event.plain_result(f"✅ 附加知识已注入，将在接下来的 {data['turns_left']} 轮对话中生效。")

    @filter.command("show_injections")
    async def show_injections(self, event: AstrMessageEvent):
        """查看当前生效的注入信息"""
        key = self._get_storage_key(event)
        data = await self.get_kv_data(key, None)
        
        if not data:
            yield event.plain_result("📭 当前会话没有生效的注入信息。")
            return

        msg = [
            "📋 当前注入信息：",
            f"🔄 剩余生效轮次: {data.get('turns_left', 0)}",
            f"📌 当前任务: {data.get('task', '无')}",
            f"📚 附加知识: {data.get('knowledge', '无')}"
        ]
        yield event.plain_result("\n".join(msg))

    @filter.command("clear_injections")
    async def clear_injections(self, event: AstrMessageEvent):
        """清除当前所有注入"""
        key = self._get_storage_key(event)
        await self.delete_kv_data(key)
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
        if not self._check_whitelist(event):
            return

        key = self._get_storage_key(event)
        data = await self.get_kv_data(key, None)

        if not data:
            return

        turns = data.get("turns_left", 0)
        if turns <= 0:
            # 轮次耗尽，清理数据
            await self.delete_kv_data(key)
            return

        # 构造注入内容
        injection_text = ""
        if data.get("task"):
            injection_text += f"\n[System Injection - Current Task]\n{data['task']}\n"
        if data.get("knowledge"):
            injection_text += f"\n[System Injection - Additional Knowledge]\n{data['knowledge']}\n"
        
        if injection_text:
            # 注入到 system prompt 中
            # 如果原 system prompt 存在，追加到后面；否则直接设置
            if req.system_prompt:
                req.system_prompt += injection_text
            else:
                req.system_prompt = injection_text
            
            # 扣除轮次
            data["turns_left"] = turns - 1
            await self.put_kv_data(key, data)
            logger.info(f"Injecting prompt for {event.unified_msg_origin}. Turns left: {data['turns_left']}")
