import re
import json
import os
from datetime import datetime, timedelta
from typing import Optional

import requests
import dateparser
from fastapi import FastAPI, Request, HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()

FEISHU_APP_ID = os.getenv("FEISHU_APP_ID")
FEISHU_APP_SECRET = os.getenv("FEISHU_APP_SECRET")
DINGTALK_APP_KEY = os.getenv("DINGTALK_APP_KEY")
DINGTALK_APP_SECRET = os.getenv("DINGTALK_APP_SECRET")

# 用户授权相关
USER_ACCESS_TOKEN_FILE = "user_access_token.txt"
USER_REFRESH_TOKEN_FILE = "user_refresh_token.txt"


def get_user_access_token():
    """从文件读取用户访问令牌"""
    try:
        with open(USER_ACCESS_TOKEN_FILE, 'r') as f:
            return f.read().strip()
    except:
        return None


def save_user_tokens(access_token, refresh_token=None):
    """保存用户访问令牌"""
    with open(USER_ACCESS_TOKEN_FILE, 'w') as f:
        f.write(access_token)
    if refresh_token:
        with open(USER_REFRESH_TOKEN_FILE, 'w') as f:
            f.write(refresh_token)


@app.get("/authorize")
def authorize():
    """生成飞书授权 URL"""
    redirect_uri = "http://localhost:8000/callback"
    scope = "calendar:calendar:readonly calendar:calendar.event:create calendar:calendar.event:update calendar:calendar.event:delete"
    url = f"https://open.feishu.cn/open-apis/authen/v1/authorize?app_id={FEISHU_APP_ID}&redirect_uri={requests.utils.quote(redirect_uri)}&scope={requests.utils.quote(scope)}"
    return {"url": url, "message": "请访问上面的 URL 进行授权，然后告诉我授权后的完整回调 URL"}


@app.get("/delete_token")
def delete_token():
    """删除用户授权 token"""
    try:
        if os.path.exists(USER_ACCESS_TOKEN_FILE):
            os.remove(USER_ACCESS_TOKEN_FILE)
        if os.path.exists(USER_REFRESH_TOKEN_FILE):
            os.remove(USER_REFRESH_TOKEN_FILE)
        return {"message": "Token 已删除，可以重新授权了"}
    except Exception as e:
        return {"error": str(e)}



@app.get("/callback")
def callback(code: str = None, redirect_uri: str = None):
    """处理飞书授权回调"""
    if not code:
        return {"error": "缺少授权码"}
    
    # 先获取 app_access_token
    app_token_url = "https://open.feishu.cn/open-apis/auth/v3/app_access_token/internal"
    app_token_data = {
        "app_id": FEISHU_APP_ID,
        "app_secret": FEISHU_APP_SECRET
    }
    app_token_resp = requests.post(app_token_url, json=app_token_data).json()
    print(f"=== App Token响应: {app_token_resp} ===")
    app_access_token = app_token_resp.get("app_access_token")
    
    if not app_access_token:
        return {"error": f"获取app_access_token失败: {app_token_resp}"}
    
    # 用 app_access_token 和 code 换取 user_access_token
    url = "https://open.feishu.cn/open-apis/authen/v1/oidc/access_token"
    headers = {
        "Authorization": f"Bearer {app_access_token}",
        "Content-Type": "application/json"
    }
    data = {
        "grant_type": "authorization_code",
        "code": code
    }
    
    resp = requests.post(url, headers=headers, json=data).json()
    print(f"=== 授权响应: {resp} ===")
    
    if resp.get("code") == 0:
        access_token = resp.get("data", {}).get("access_token")
        refresh_token = resp.get("data", {}).get("refresh_token")
        save_user_tokens(access_token, refresh_token)
        return {"success": True, "message": "授权成功！可以关闭此页面了。"}
    else:
        return {"error": f"授权失败: {resp}"}



def get_feishu_user_access_token():
    """获取用户访问令牌（优先从文件读取）"""
    token = get_user_access_token()
    if token:
        return token
    return None


def get_feishu_tenant_access_token():
    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    headers = {"Content-Type": "application/json; charset=utf-8"}
    data = {"app_id": FEISHU_APP_ID, "app_secret": FEISHU_APP_SECRET}
    resp = requests.post(url, headers=headers, json=data).json()
    if resp.get("code") != 0:
        raise Exception(f"飞书获取token失败: {resp}")
    return resp["tenant_access_token"]


def get_dingtalk_access_token():
    url = f"https://oapi.dingtalk.com/gettoken?appkey={DINGTALK_APP_KEY}&appsecret={DINGTALK_APP_SECRET}"
    resp = requests.get(url).json()
    if resp.get("errcode") != 0:
        raise Exception(f"钉钉获取token失败: {resp}")
    return resp["access_token"]


def parse_time_text(text: str, base_date=None):
    """解析时间文本，支持中英文表达"""
    base = base_date or datetime.now()
    
    # 尝试使用 dateparser (主要处理英文)
    settings = {
        'PREFER_DATES_FROM': 'future',
        'RELATIVE_BASE': base,
        'TIMEZONE': 'Asia/Shanghai',
        'PREFER_DAY_OF_MONTH': 'first'
    }
    parsed = dateparser.parse(text, settings=settings)
    if parsed:
        return parsed
    
    # 中文时间解析
    parsed_cn = parse_chinese_time(text, base)
    if parsed_cn:
        return parsed_cn
    return parsed


def parse_chinese_time(text: str, base_date=None):
    """解析中文时间表达"""
    import re
    base = base_date or datetime.now()
    original_text = text
    
    # 星期映射
    week_map = {'周一': 1, '周二': 2, '周三': 3, '周四': 4, '周五': 5, '周六': 6, '周日': 0}
    
    # 日期词映射
    day_map = {'今天': 0, '明天': 1, '后天': 2}
    
    # 提取下午/上午
    is_pm = False
    if '下午' in text or '晚上' in text:
        is_pm = True
        text = text.replace('下午', '').replace('晚上', '')
    if '上午' in text or '早上' in text or '早晨' in text or '中午' in text:
        text = text.replace('上午', '').replace('早上', '').replace('早晨', '').replace('中午', '')
    
    # 处理"点半"的情况
    half_hour_match = re.search(r'(\d+)点半', text)
    if half_hour_match:
        text = text.replace(half_hour_match.group(0), f"{half_hour_match.group(1)}点30分")
    
    # 处理"X点后"的情况
    after_time_match = re.search(r'(\d+)点后', text)
    if after_time_match:
        text = text.replace(after_time_match.group(0), f"{after_time_match.group(1)}点")
    
    # 解析相对日期
    for keyword, days in day_map.items():
        if keyword in text:
            target_date = base + timedelta(days=days)
            text = text.replace(keyword, '').strip()
            return combine_date_time(target_date, text, is_pm)
    
    # 解析 X月X日 格式
    month_day_match = re.search(r'(\d+)月(\d+)日', text)
    if month_day_match:
        month = int(month_day_match.group(1))
        day = int(month_day_match.group(2))
        year = base.year
        if month < base.month or (month == base.month and day < base.day):
            year += 1
        target_date = datetime(year, month, day)
        time_part = text.replace(month_day_match.group(0), '').strip()
        return combine_date_time(target_date, time_part, is_pm)
    
    # 如果没有找到日期词，只有时间，使用 base_date 的日期
    time_only_match = re.search(r'(\d{1,2}):?(\d{0,2})点?', text)
    if time_only_match and base_date:
        return combine_date_time(base_date.replace(hour=0, minute=0, second=0, microsecond=0), text, is_pm)
    
    return None


def extract_single_schedule(title: str, time_text: str):
    """解析单个日程的标题和时间文本"""
    result = {"title": title, "start_time": None, "end_time": None}
    
    if not time_text:
        return None
    
    separators = ["到", "至", "-", "~"]
    for sep in separators:
        if sep in time_text:
            parts = time_text.split(sep, 1)
            start_str = parts[0].strip()
            end_str = parts[1].strip()
            # 清理结束时间中的逗号等
            end_str = end_str.split('，')[0].split(',')[0].strip()
            start_dt = parse_time_text(start_str)
            if start_dt:
                end_dt = parse_time_text(end_str, base_date=start_dt)
                if end_dt and end_dt <= start_dt:
                    if end_dt.hour < 12 and start_dt.hour >= 12:
                        end_dt = end_dt + timedelta(hours=12)
                    if end_dt <= start_dt:
                        end_dt = end_dt + timedelta(hours=12)
            else:
                end_dt = None
            
            if start_dt and end_dt:
                result["start_time"] = start_dt
                result["end_time"] = end_dt
                return result
            break
    
    single_dt = parse_time_text(time_text)
    if single_dt:
        result["start_time"] = single_dt
        result["end_time"] = single_dt + timedelta(hours=1)
        return result
    
    return None


def extract_single_from_mixed(text: str, prev_title=None):
    """从混合文本中解析日程（时间在前，标题在后，如：明天晚上8点到9点，吃夜宵）"""
    import re
    # 匹配 "时间 到 时间，标题" 或 "时间，标题"
    separators = ["到", "至", "-", "~"]
    
    # 判断是否有"晚上"或"下午"
    is_pm = '晚上' in text or '下午' in text
    
    for sep in separators:
        if sep in text:
            # 尝试找到分隔符前的部分作为时间，后面的作为标题
            parts = text.split(sep, 1)
            start_str = parts[0].strip()
            remaining = parts[1].strip()
            
            # 提取结束时间（到逗号或句尾）
            end_part = remaining.split('，')[0].split(',')[0].split('。')[0].strip()
            
            # 提取标题（逗号后面的部分）
            if '，' in remaining:
                title = remaining.split('，', 1)[1].strip()
            elif ',' in remaining:
                title = remaining.split(',', 1)[1].strip()
            else:
                # 没有逗号，说明整个文本都是时间格式，不是"时间，标题"格式
                # 如果有前一行标题，则用前一行标题
                if prev_title:
                    title = prev_title
                else:
                    # 没有前一行标题，返回None，让外部用其他方式处理
                    return None
            
            start_dt = parse_time_text(start_str)
            # 如果整句话有"晚上/下午"，结束时间也需要加12小时
            end_dt = parse_time_text(end_part, base_date=start_dt) if start_dt else None
            if end_dt and is_pm and end_dt.hour < 12:
                end_dt = end_dt + timedelta(hours=12)
            
            if start_dt and end_dt:
                # 如果结束时间早于开始时间，再加12小时
                if end_dt <= start_dt:
                    end_dt = end_dt + timedelta(hours=12)
                return {"title": title, "start_time": start_dt, "end_time": end_dt}
    
    return None


def extract_multiple_schedules(text: str):
    """从文本中提取多个日程"""
    lines = [l.strip() for l in text.strip().split('\n') if l.strip()]
    if not lines:
        return []
    
    schedules = []
    current_title = None
    current_time_lines = []
    prev_title = None  # 保存前一个标题
    
    # 时间相关的关键词
    time_keywords = ['今天', '明天', '后天', '上午', '下午', '晚上', '中午', '早上', '点', '月', '日', '半']
    separators = ['到', '至', '-', '~']
    
    def is_time_line(line):
        return any(kw in line for kw in time_keywords) or any(sep in line for sep in separators)
    
    for line in lines:
        # 首先检查是否是 "时间，标题" 格式（逗号分隔）
        mixed_result = extract_single_from_mixed(line, prev_title)
        if mixed_result and mixed_result.get('title'):
            schedules.append(mixed_result)
            prev_title = mixed_result['title']  # 更新前一个标题
            continue
        
        if is_time_line(line):
            if current_title and current_time_lines:
                time_text = ' '.join(current_time_lines)
                info = extract_single_schedule(current_title, time_text)
                if info:
                    schedules.append(info)
            current_time_lines = [line]
        else:
            if current_title and current_time_lines:
                time_text = ' '.join(current_time_lines)
                info = extract_single_schedule(current_title, time_text)
                if info:
                    schedules.append(info)
            current_title = line
            prev_title = line  # 保存当前行作为前一个标题
            current_time_lines = []
    
    # 处理最后一批
    if current_title and current_time_lines:
        time_text = ' '.join(current_time_lines)
        info = extract_single_schedule(current_title, time_text)
        if info:
            schedules.append(info)
    
    return schedules


def combine_date_time(date_obj, time_str, is_pm=False):
    """将日期对象和时间字符串组合"""
    import re
    hour, minute = 9, 0  # 默认值
    
    # 提取时间
    time_match = re.search(r'(\d{1,2}):?(\d{0,2})点?', time_str)
    if time_match:
        hour = int(time_match.group(1))
        minute = int(time_match.group(2)) if time_match.group(2) else 0
    
    print(f"=== combine_date_time: 输入 date={date_obj}, time_str={time_str}, is_pm={is_pm}, 提取hour={hour} ===")
    
    # 处理下午
    if is_pm and hour < 12:
        hour += 12
        print(f"=== 下午时间+12小时, 新hour={hour} ===")
    
    result = date_obj.replace(hour=hour, minute=minute, second=0, microsecond=0)
    print(f"=== combine_date_time结果: {result} ===")
    return result


def extract_schedule_info(text: str):
    lines = [l.strip() for l in text.strip().split('\n') if l.strip()]
    print(f"=== 按行拆分结果: {lines} ===")  # 调试：看看文本被拆成了几行

    if not lines:
        print("错误：文本为空或无法按行拆分")
        return None

    title = lines[0]
    result = {"title": title, "start_time": None, "end_time": None}
    full_text = " ".join(lines[1:])

    if not full_text:
        print("错误：缺少时间信息，只有标题")
        return None

    print(f"=== 标题: {title}, 时间文本: {full_text} ===")

    separators = ["到", "至", "-", "~"]
    for sep in separators:
        if sep in full_text:
            parts = full_text.split(sep, 1)
            start_str = parts[0].strip()
            end_str = parts[1].strip()
            start_dt = parse_time_text(start_str)
            if start_dt:
                end_dt = parse_time_text(end_str, base_date=start_dt)
                # 如果结束时间早于开始时间，认为是同一天的下半天
                if end_dt and end_dt <= start_dt:
                    # 如果结束时间是凌晨/早上，假设是下午
                    if end_dt.hour < 12 and start_dt.hour >= 12:
                        end_dt = end_dt + timedelta(hours=12)
                    # 如果结束时间仍然早于开始时间，加12小时
                    if end_dt <= start_dt:
                        end_dt = end_dt + timedelta(hours=12)
            else:
                print(f"错误：时间解析失败，start_str={start_str}")
                end_dt = None
            
            if start_dt and end_dt:
                result["start_time"] = start_dt
                result["end_time"] = end_dt
                return result
            break

    single_dt = parse_time_text(full_text)
    if single_dt:
        result["start_time"] = single_dt
        result["end_time"] = single_dt + timedelta(hours=1)
        return result

    print("错误：无法从时间文本中解析出任何时间")
    return None


def create_feishu_event(summary, start_time: datetime, end_time: datetime):
    # 优先使用用户授权的 token
    user_token = get_feishu_user_access_token()
    if user_token:
        # 获取用户的日历列表
        headers = {"Authorization": f"Bearer {user_token}"}
        resp = requests.get(
            "https://open.feishu.cn/open-apis/calendar/v4/calendars",
            headers=headers
        ).json()
        print(f"=== 获取日历列表响应: {resp} ===")
        
        # 找到主日历
        calendar_id = None
        if resp.get("code") == 0:
            calendars = resp.get("data", {}).get("calendar_list", [])
            for cal in calendars:
                if cal.get("summary") == "我的日历" or cal.get("type") == "primary":
                    calendar_id = cal.get("calendar_id")
                    print(f"=== 找到主日历: {calendar_id} ===")
                    break
        
        if not calendar_id:
            print("=== 未找到主日历，使用 primary ===")
            calendar_id = "primary"
        
        # 创建日程到用户的日历
        url = f"https://open.feishu.cn/open-apis/calendar/v4/calendars/{calendar_id}/events"
        payload = {
            "summary": summary,
            "start_time": {
                "timestamp": int(start_time.timestamp()),
                "timezone": "Asia/Shanghai"
            },
            "end_time": {
                "timestamp": int(end_time.timestamp()),
                "timezone": "Asia/Shanghai"
            }
        }
        resp = requests.post(url, headers=headers, json=payload).json()
        if resp.get("code") != 0:
            print(f"飞书创建日程失败: {resp}")
        return resp
    else:
        print("=== 未授权用户，跳过飞书日历创建 ===")
        return {"code": -1, "msg": "用户未授权"}


def create_dingtalk_event(summary, start_time: datetime, end_time: datetime):
    token = get_dingtalk_access_token()
    url = f"https://oapi.dingtalk.com/topapi/calendar/v2/event/create?access_token={token}"
    headers = {"Content-Type": "application/json"}
    start_ts = int(start_time.timestamp() * 1000)
    end_ts = int(end_time.timestamp() * 1000)
    payload = {
        "summary": summary,
        "start_time": {
            "timestamp": start_ts,
            "timezone": "Asia/Shanghai"
        },
        "end_time": {
            "timestamp": end_ts,
            "timezone": "Asia/Shanghai"
        }
    }
    resp = requests.post(url, headers=headers, json=payload).json()
    if resp.get("errcode") != 0:
        print(f"钉钉创建日程失败: {resp}")
    return resp



def delete_feishu_event(event_id: str, calendar_id: str):
    """删除飞书日程"""
    user_token = get_feishu_user_access_token()
    if not user_token:
        return {"code": -1, "msg": "用户未授权"}
    
    url = f"https://open.feishu.cn/open-apis/calendar/v4/calendars/{calendar_id}/events/{event_id}"
    headers = {"Authorization": f"Bearer {user_token}"}
    resp = requests.delete(url, headers=headers).json()
    if resp.get("code") != 0:
        print(f"飞书删除日程失败: {resp}")
    return resp


def delete_dingtalk_event(event_id: str):
    """删除钉钉日程"""
    token = get_dingtalk_access_token()
    url = f"https://oapi.dingtalk.com/topapi/calendar/v2/event/delete?access_token={token}"
    headers = {"Content-Type": "application/json"}
    data = {"event_id": event_id}
    resp = requests.post(url, headers=headers, json=data).json()
    if resp.get("errcode") != 0:
        print(f"钉钉删除日程失败: {resp}")
    return resp


def update_feishu_event(event_id: str, calendar_id: str, summary=None, start_time=None, end_time=None):
    """修改飞书日程"""
    user_token = get_feishu_user_access_token()
    if not user_token:
        return {"code": -1, "msg": "用户未授权"}
    
    url = f"https://open.feishu.cn/open-apis/calendar/v4/calendars/{calendar_id}/events/{event_id}"
    headers = {"Authorization": f"Bearer {user_token}", "Content-Type": "application/json"}
    payload = {}
    if summary:
        payload["summary"] = summary
    if start_time:
        payload["start_time"] = {"timestamp": int(start_time.timestamp()), "timezone": "Asia/Shanghai"}
    if end_time:
        payload["end_time"] = {"timestamp": int(end_time.timestamp()), "timezone": "Asia/Shanghai"}
    
    resp = requests.patch(url, headers=headers, json=payload).json()
    if resp.get("code") != 0:
        print(f"飞书修改日程失败: {resp}")
    return resp


def update_dingtalk_event(event_id: str, summary=None, start_time=None, end_time=None):
    """修改钉钉日程"""
    token = get_dingtalk_access_token()
    url = f"https://oapi.dingtalk.com/topapi/calendar/v2/event/update?access_token={token}"
    headers = {"Content-Type": "application/json"}
    payload = {"event_id": event_id}
    if summary:
        payload["summary"] = summary
    if start_time:
        payload["start_time"] = {"timestamp": int(start_time.timestamp() * 1000), "timezone": "Asia/Shanghai"}
    if end_time:
        payload["end_time"] = {"timestamp": int(end_time.timestamp() * 1000), "timezone": "Asia/Shanghai"}
    
    resp = requests.post(url, headers=headers, json=payload).json()
    if resp.get("errcode") != 0:
        print(f"钉钉修改日程失败: {resp}")
    return resp


def get_user_events(start_date: datetime, end_date: datetime):
    """获取用户日期范围内的所有日程"""
    user_token = get_feishu_user_access_token()
    if not user_token:
        return []
    
    headers = {"Authorization": f"Bearer {user_token}"}
    events = []
    
    # 获取日历列表
    resp = requests.get("https://open.feishu.cn/open-apis/calendar/v4/calendars", headers=headers).json()
    if resp.get("code") != 0:
        return []
    
    calendars = resp.get("data", {}).get("calendar_list", [])
    
    for cal in calendars:
        calendar_id = cal.get("calendar_id")
        if not calendar_id:
            continue
        
        # 获取每个日历的事件
        url = f"https://open.feishu.cn/open-apis/calendar/v4/calendars/{calendar_id}/events"
        params = {
            "start_time": int(start_date.timestamp()),
            "end_time": int(end_date.timestamp()),
            "limit": 100
        }
        resp = requests.get(url, headers=headers, params=params).json()
        
        if resp.get("code") == 0:
            event_list = resp.get("data", {}).get("items", [])
            for event in event_list:
                events.append({
                    "event_id": event.get("event_id"),
                    "calendar_id": calendar_id,
                    "summary": event.get("summary"),
                    "start_time": event.get("start_time", {}).get("timestamp"),
                    "end_time": event.get("end_time", {}).get("timestamp")
                })
    
    return events


def parse_delete_intent(text: str):
    """解析删除日程的意图"""
    delete_keywords = ['取消', '删除', '不要了', '删掉', '清除', '删了']
    
    for kw in delete_keywords:
        if kw in text:
            if '今天' in text:
                return {'time': 'today'}
            elif '明天' in text:
                return {'time': 'tomorrow'}
            elif '后天' in text:
                return {'time': 'day_after_tomorrow'}
            elif '这周' in text:
                return {'time': 'this_week'}
            elif '全部' in text or '所有' in text:
                return {'time': 'all'}
            else:
                return {'time': 'all'}
    return None


def parse_modify_intent(text: str):
    """解析修改日程的意图"""
    modify_keywords = ['改时间', '修改时间', '改一下', '改成', '修改', '改', '更新']
    
    for kw in modify_keywords:
        if kw in text:
            return {'action': 'modify'}
    return None


class FeishuEvent(BaseModel):
    schema: Optional[str] = None
    header: Optional[dict] = None
    event: Optional[dict] = None
    challenge: Optional[str] = None
    token: Optional[str] = None


@app.post("/")
async def handle_event(event_data: FeishuEvent):
    print("=== 收到飞书事件 ===")
    print(f"event_data: {event_data}")
    print(f"event_data.event: {event_data.event}")
    print(f"event_data.schema: {event_data.schema}")
    print(f"event_data.json(): {event_data.json()}")
    print("====================")

    if event_data.challenge:
        return {"challenge": event_data.challenge}

    event = event_data.event
    if not event:
        return {"code": 0}

    # 从 header 获取 event_type（飞书把事件类型放在 header 里）
    event_type = event.get("type") or (event_data.header.get("event_type") if event_data.header else None)
    print(f"=== event_type检查: {event_type} ===")
    
    if event_type == "im.message.receive_v1":
        print(f"=== event_type检查: {event_type} ===")
        message = event.get("message")
        print(f"=== message检查: message={message} ===")
        if not message or message.get("message_type") != "text":
            print(f"=== message类型不匹配: message_type={message.get('message_type') if message else None} ===")
            return {"code": 0}

        content_str = message["content"]
        print(f"=== content原始: {content_str} ===")
        content_json = json.loads(content_str)
        text = content_json.get("text", "")
        text = text.replace('\\n', '\n')
        print(f"=== 提取的text: {repr(text)} ===")

        try:
            # 先检查是否是删除意图
            delete_intent = parse_delete_intent(text)
            if delete_intent:
                print(f"=== 检测到删除意图: {delete_intent} ===")
                now = datetime.now()
                if delete_intent['time'] == 'today':
                    start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
                    end_date = now.replace(hour=23, minute=59, second=59)
                elif delete_intent['time'] == 'tomorrow':
                    start_date = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
                    end_date = start_date.replace(hour=23, minute=59, second=59)
                elif delete_intent['time'] == 'day_after_tomorrow':
                    start_date = (now + timedelta(days=2)).replace(hour=0, minute=0, second=0, microsecond=0)
                    end_date = start_date.replace(hour=23, minute=59, second=59)
                else:
                    start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
                    end_date = (now + timedelta(days=30)).replace(hour=23, minute=59, second=59)
                
                events = get_user_events(start_date, end_date)
                deleted_count = 0
                for evt in events:
                    delete_feishu_event(evt['event_id'], evt['calendar_id'])
                    deleted_count += 1
                return {"code": 0, "msg": f"已删除 {deleted_count} 个日程"}
            
            # 检查是否是修改意图
            modify_intent = parse_modify_intent(text)
            if modify_intent:
                new_schedules = extract_multiple_schedules(text)
                if new_schedules and len(new_schedules) > 0:
                    now = datetime.now()
                    start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
                    end_date = now.replace(hour=23, minute=59, second=59)
                    events = get_user_events(start_date, end_date)
                    if events:
                        update_feishu_event(
                            events[0]['event_id'],
                            events[0]['calendar_id'],
                            summary=new_schedules[0].get('title'),
                            start_time=new_schedules[0].get('start_time'),
                            end_time=new_schedules[0].get('end_time')
                        )
                        return {"code": 0, "msg": "日程已修改"}
                return {"code": 0, "msg": "未找到需要修改的日程"}
            
            # 尝试批量解析多个日程
            schedules = extract_multiple_schedules(text)
            print(f"=== 批量解析结果: {schedules} ===")
            
            if len(schedules) > 1:
                feishu_count = 0
                dingtalk_count = 0
                for schedule in schedules:
                    feishu_res = create_feishu_event(
                        schedule["title"], schedule["start_time"], schedule["end_time"]
                    )
                    if feishu_res.get("code") == 0:
                        feishu_count += 1
                    dingtalk_res = create_dingtalk_event(
                        schedule["title"], schedule["start_time"], schedule["end_time"]
                    )
                    if dingtalk_res.get("errcode") == 0:
                        dingtalk_count += 1
                return {"code": 0, "msg": f"已创建 {len(schedules)} 个日程 (飞书{feishu_count}个, 钉钉{dingtalk_count}个)"}
            elif len(schedules) == 1:
                schedule = schedules[0]
                feishu_res = create_feishu_event(
                    schedule["title"], schedule["start_time"], schedule["end_time"]
                )
                dingtalk_res = create_dingtalk_event(
                    schedule["title"], schedule["start_time"], schedule["end_time"]
                )
                return {"code": 0, "msg": "日程已创建"}
            else:
                info = extract_schedule_info(text)
                print(f"=== 原解析器结果: {info} ===")
                if info:
                    feishu_res = create_feishu_event(
                        info["title"], info["start_time"], info["end_time"]
                    )
                    dingtalk_res = create_dingtalk_event(
                        info["title"], info["start_time"], info["end_time"]
                    )
                    return {"code": 0, "msg": "日程已创建"}
                else:
                    print(f"未能解析的原始文本为: {repr(text)}")
        except Exception as e:
            print(f"创建日程失败，异常信息: {e}")

    return {"code": 0}


@app.get("/")
def health():
    return {"status": "ok"}