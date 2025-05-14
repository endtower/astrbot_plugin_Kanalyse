import os.path
from datetime import datetime
import json
import markdown  # 引入markdown库
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger

tmpl = '''
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <style>
        body {
            font-family: Arial, sans-serif;
            font-size: 14px; /* 调整整体文字大小 */
        }
        h1, h2, h3 {
            font-size: 1.5em; /* 调整标题大小 */
        }
        table {
            width: 100%;
            border-collapse: collapse;
            font-size: 1em; /* 调整表格文字大小 */
        }
        th, td {
            border: 1px solid #ccc;
            padding: 8px;
        }
        pre {
            background-color: #f4f4f4;
            padding: 10px;
            border: 1px solid #ccc;
            border-radius: 4px;
            font-size: 1em; /* 调整代码块文字大小 */
        }
    </style>
</head>
<body>
    {{ html_content }}
</body>
</html>
'''

@register("astrbot_plugin_Kanalyse", "End_tower", "冲突调停", "1.01")
# 聊天记录总结插件主类，继承自Star基类
class ChatSummary(Star):
    # 初始化聊天分析插件实例，继承Star基类
    def __init__(self, context: Context):
        super().__init__(context)

    # 注册分析聊天记录指令的装饰器。发送 `/分析聊天记录` 触发消息分析功能
    @filter.command("分析聊天记录")  # 消息历史获取与处理
    async def summary(self, event: AstrMessageEvent, count: int = None, debug:str=None):
        from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent
        assert isinstance(event, AiocqhttpMessageEvent)
        client = event.bot

        # 构造获取群消息历史的请求参数
        payloads = {
          "group_id": event.get_group_id(),
          "message_seq": "0",
          "count": 10,
          "reverseOrder": True
        }

        # 调用API获取群聊历史消息
        # 检查是否为群聊环境
        if not event.get_group_id():
            yield event.plain_result("当前不为群聊环境")
            return

        ret = await client.api.call_action("get_group_msg_history", **payloads)

        # 处理消息历史记录，对其格式化
        messages = ret.get("messages", [])
        chat_lines = []
        
        # 找到最近的合并转发消息
        latest_forward = None
        for msg in messages:
            for part in msg['message']:
                if part['type'] == 'forward':
                    latest_forward = part['data']['id']
                    break
            if latest_forward:
                break
                
        # 如果找到合并转发消息,处理它
        if latest_forward:
            forward_payloads = {
                "message_id": latest_forward
            }
            forward_ret = await client.api.call_action("get_forward_msg", **forward_payloads)
            forward_messages = forward_ret.get("messages", [])
            for forward_msg in forward_messages:
                forward_sender = forward_msg.get('sender', {})
                forward_nickname = forward_sender.get('nickname', '未知用户')
                forward_msg_time = datetime.fromtimestamp(forward_msg.get('time', 0))
                forward_text = ""
                for forward_part in forward_msg['message']:
                    if forward_part['type'] == 'text':
                        forward_text += forward_part['data']['text'].strip() + " "
                if forward_text:
                    chat_lines.append(f"[{forward_msg_time}]「{forward_nickname}」: {forward_text.strip()}")

        # 生成最终prompt
        msg = "\n".join(chat_lines)
        if not msg:
            yield event.plain_result("未获取到任何消息记录")
            return
                
        # LLM处理流程
        def load_prompt():
            with open(os.path.join('data','config','astrbot_plugin_kanalyse_config.json'), 'r', encoding='utf-8-sig') as a:
                config = json.load(a)
                prompt_str = config.get('prompt',{})
                return str(prompt_str.replace('\\n','\n'))

        # 调用LLM生成总结内容
        llm_response = await self.context.get_using_provider().text_chat(
            prompt=load_prompt(),
            contexts=[
                {"role": "user", "content": str(msg)}
            ],
        )

        # 输出LLM最终总结内容，发送总结消息
        if not llm_response:
            yield event.plain_result("LLM处理失败，无法生成总结")
            return

        # 解析Markdown文本为HTML
        markdown_text = llm_response.completion_text     

        # 定义一个函数来去除首尾的 ```
        cleaned_text = markdown_text.replace("```", "")






                # 解析Markdown文本，启用常用扩展
        html_content = markdown.markdown(cleaned_text, extensions=[
            'fenced_code', 
            'tables', 
            'codehilite', 
            'sane_lists'  # 重新启用
        ])

        # 自定义 HTML 模板，使用 CSS 调整样式


        # 准备 Jinja2 渲染数据
        render_data = {"html_content": html_content}

        # 使用AstrBot的text_to_image方法将HTML内容转换为图片
        url = await self.html_render(tmpl, render_data)

        # 返回生成的图片
        yield event.image_result(url)

    @filter.command("现场分析")
    async def chat_analysis(self, event: AstrMessageEvent, count: int = None, debug:str=None):
        """触发消息总结，命令加空格，后面跟获取聊天记录的数量即可（例如“ /消息总结 20 ”）"""
        from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent
        assert isinstance(event, AiocqhttpMessageEvent)
        client = event.bot

        # 检查是否传入了要总结的聊天记录数量，未传入则返回错误，并终止事件传播
        if count is None:
            yield event.plain_result("\n请按照「 /消息总结 [要总结的聊天记录数量] 」格式发送\n例如「 /消息总结 114 」~")
            event.stop_event()

        # 构造获取群消息历史的请求参数
        payloads = {
          "group_id": event.get_group_id(),
          "message_seq": "0",
          "count": count,
          "reverseOrder": True
        }

        # 调用API获取群聊历史消息
        ret = await client.api.call_action("get_group_msg_history", **payloads)

        # 处理消息历史记录，对其格式化
        messages = ret.get("messages", [])
        chat_lines = []
        for msg in messages:
            # 解析发送者信息
            sender = msg.get('sender', {})
            nickname = sender.get('nickname', '未知用户')
            msg_time = datetime.fromtimestamp(msg.get('time', 0))  # 防止time字段缺失
            # 提取所有文本内容（兼容多段多类型文本消息）
            message_text = ""
            for part in msg['message']:
                if part['type'] == 'text':
                    message_text += part['data']['text'].strip() + " "
                elif part['type'] == 'json':  # 处理JSON格式的分享卡片等特殊消息
                    try:
                        json_content = json.loads(part['data']['data'])
                        if 'desc' in json_content.get('meta', {}).get('news', {}):
                            message_text += f"[分享内容]{json_content['meta']['news']['desc']} "
                    except:
                        pass

                # 表情消息处理
                elif part['type'] == 'face':
                    message_text += "[表情] "

            # 生成标准化的消息记录格式
            if message_text:
                chat_lines.append(f"[{msg_time}]「{nickname}」: {message_text.strip()}")

        # 生成最终prompt
        msg = "\n".join(chat_lines)

        # 判断是否为管理员，从配置文件加载管理员列表
        def _load_admins():
            with open(os.path.join('data', 'cmd_config.json'), 'r', encoding='utf-8-sig') as f:
                config = json.load(f)
                return config.get('admins_id', [])

        def is_admin(user_id):
            return str(user_id) in _load_admins()

        # LLM处理流程
        def load_prompt():
            with open(os.path.join('data','config','astrbot_plugin_kanalyse_config.json'), 'r', encoding='utf-8-sig') as a:
                config = json.load(a)
                prompt_str = config.get('prompt',{})
                return str(prompt_str.replace('\\n','\n'))

        # 调用LLM生成总结内容
        llm_response = await self.context.get_using_provider().text_chat(
            prompt=load_prompt(),
            contexts=[
                {"role": "user", "content": str(msg)}
            ],
        )

        # 调试模式处理逻辑（仅管理员可用）
        if debug == "debug" or debug == "Debug":
            if not is_admin(str(event.get_sender_id())):  # 验证用户是否为管理员
                yield event.plain_result("您无权使用该命令！")
                return
            else:
                logger.info(f"prompt: {load_prompt()}") # 调试输出prompt和llm_response到控制台
                logger.info(f"llm_response: {llm_response}")
                yield event.plain_result(str(f"prompt已通过Info Logs在控制台输出，可前往Astrbot控制台查看。以下为格式化后的聊天记录Debug输出：\n{msg}"))

        # 输出LLM最终总结内容，发送总结消息







        markdown_text = llm_response.completion_text


                # 解析Markdown文本，启用常用扩展
        html_content = markdown.markdown(markdown_text, extensions=[
            'fenced_code', 
            'tables', 
            'codehilite', 
            'sane_lists'  # 重新启用
        ])

        # 自定义 HTML 模板，使用 CSS 调整样式
        tmpl = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <style>
        body {
            font-family: Arial, sans-serif;
            font-size: 14px; /* 调整整体文字大小 */
        }
        h1, h2, h3 {
            font-size: 1.5em; /* 调整标题大小 */
        }
        table {
            width: 100%;
            border-collapse: collapse;
            font-size: 1em; /* 调整表格文字大小 */
        }
        th, td {
            border: 1px solid #ccc;
            padding: 8px;
        }
        pre {
            background-color: #f4f4f4;
            padding: 10px;
            border: 1px solid #ccc;
            border-radius: 4px;
            font-size: 1em; /* 调整代码块文字大小 */
        }
    </style>
</head>
<body>
    {{ html_content }}
</body>
</html>
"""

        # 准备 Jinja2 渲染数据
        render_data = {"html_content": html_content}

        # 使用AstrBot的text_to_image方法将HTML内容转换为图片
        url = await self.html_render(tmpl, render_data)

        # 返回生成的图片
        yield event.image_result(url)
        
