import re
import time
from typing import Optional

import requests
import os
import csv


def config():
    return {
        "name": "1688链接验证",
        "version": "1.0.0",
        "description": "验证1688链接状态（失效/未失效/天猫），自动登录淘宝获取Cookie，批量检测后输出CSV",
        "category": "链接检查",
        "params": [
            {
                "key": "账号",
                "type": "text",
                "label": "淘宝账号",
                "required": True,
                "help": "用于登录淘宝知识产权平台的账号",
            },
            {
                "key": "密码",
                "type": "text",
                "label": "淘宝密码",
                "required": True,
                "help": "用于登录的密码",
            },
            {
                "key": "间隔",
                "type": "number",
                "label": "请求间隔(秒)",
                "default": 5,
                "min": 1,
                "max": 60,
                "help": "每批次请求之间的等待时间，避免被检测",
            },
            {
                "key": "链接文件",
                "type": "file",
                "label": "链接列表文件",
                "required": True,
                "help": "每行一个1688链接的txt文件",
            },
            {
                "key": "输出文件名",
                "type": "text",
                "label": "输出文件名",
                "default": "1688链接验证结果.csv",
                "help": "结果保存到桌面，填写文件名即可",
            },
        ],
        "requirements": ["DrissionPage>=4.0", "requests"],
        "timeout": 3600,
    }


def 清除代理():
    os.environ.pop('http_proxy', None)
    os.environ.pop('https_proxy', None)
    os.environ.pop('HTTP_PROXY', None)
    os.environ.pop('HTTPS_PROXY', None)
    os.environ.pop('no_proxy', None)
    os.environ.pop('NO_PROXY', None)
    os.environ['no_proxy'] = '*'


def 清洗数据(data):
    formatted_data = []
    for item in data.get('data', {}).get('links', []):
        链接 = item.get('link', '')
        状态1 = item.get('valid', '')
        详情 = item.get('invalidReason', '')

        if 详情 == "您选择的投诉站点与被投诉链接所属站点不匹配，请重新选择投诉站点！":
            状态 = "天猫"
        elif 状态1 == True:
            状态 = "未失效"
        elif 状态1 == False:
            状态 = "失效"
        else:
            状态 = "未知"

        formatted_data.append([链接, 状态])

    return formatted_data


def 验证淘宝链接(链接, cookies, token):
    headers = {
        'accept': 'application/json, text/plain, */*',
        'accept-language': 'zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6',
        'bx-v': '2.5.28',
        'content-type': 'application/x-www-form-urlencoded; charset=UTF-8',
        'dnt': '1',
        'origin': 'https://ipp.taobao.com',
        'priority': 'u=1, i',
        'referer': 'https://ipp.taobao.com/ippCenter.htm',
        'sec-ch-ua': '"Not(A:Brand";v="99", "Microsoft Edge";v="133", "Chromium";v="133"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Windows"',
        'sec-fetch-dest': 'empty',
        'sec-fetch-mode': 'cors',
        'sec-fetch-site': 'same-origin',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36 Edg/133.0.0.0',
        'cookie': cookies,
    }

    data = {
        'rightInfo': '2163546',
        'entityType': 'item',
        'platform': 'cbu',
        'links': 链接,
        'reason': 'frontReason.trademark.item.ymxxzbdsyqlrsb',
        'complaintSource': 'ipp',
        'language': 'cn',
        '_tb_token_': token,
    }

    response = requests.post('https://ipp.taobao.com/complaint/complaintSubmission/checkLinks.json', headers=headers,
                             data=data)
    return 清洗数据(response.json())


def 格式化1688链接(原始链接):
    匹配结果 = re.search(r'offer/(\d+)\.html', 原始链接)
    if 匹配结果:
        链接ID = 匹配结果.group(1)
        return f'http://detail.1688.com/offer/{链接ID}.html'
    return None


def 从文件读取并格式化链接(文件路径):
    try:
        with open(文件路径, 'r', encoding='utf-8') as 文件:
            链接列表 = 文件.readlines()
    except Exception as e:
        print(f"读取文件失败: {e}")
        return []

    链接列表 = [链接.strip() for 链接 in 链接列表]
    if not 链接列表:
        print("文件中没有链接")
        return []

    格式化后的链接 = []
    for i in range(0, len(链接列表), 300):
        格式化后的分组链接 = [格式化1688链接(链接) for 链接 in 链接列表[i:i + 300]]
        格式化后的分组链接 = [链接 for 链接 in 格式化后的分组链接 if 链接]
        if 格式化后的分组链接:
            格式化后的链接.append(r'\n'.join(格式化后的分组链接))

    return 格式化后的链接


def 写入CSV(数据, 输出文件路径):
    with open(输出文件路径, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(['链接', '状态'])
        writer.writerows(数据)


def 处理淘宝链接数据(文件路径, 输出文件路径, 间隔, cookies, token):
    格式化后的链接 = 从文件读取并格式化链接(文件路径)
    all_data = []
    处理的链接数 = 0

    for 链接 in 格式化后的链接:
        all_data.extend(验证淘宝链接(链接, cookies, token))
        处理的链接数 += 1 * 300
        print(f"已处理第 {处理的链接数} 个链接")
        time.sleep(间隔)

    写入CSV(all_data, 输出文件路径)


def 获取token值(tab):
    js = '''
    function 获取CsrfToken() {
        if (window.GlobalConfig && window.GlobalConfig.csrfToken) {
            return window.GlobalConfig.csrfToken;
        } else {
            return null;
        }
    }
    return 获取CsrfToken();
    '''
    return tab.run_js(js)


def 转换为cookie格式(cookie_dict):
    cookie_keys = [
        't', 'arms_uid', 'cna', 'xlly_s', '3PcFlag', '_tb_token_', 'mtop_partitioned_detect',
        '_m_h5_tk', '_m_h5_tk_enc', 'cookie2', 'asip_user_tmp', 'tfstk', 'isg'
    ]
    cookie_list = []
    for key in cookie_keys:
        if key in cookie_dict:
            cookie_list.append(f"{key}={cookie_dict[key]}")
    return '; '.join(cookie_list)


def 取账号cookie(账号, 密码):
    from DrissionPage import ChromiumOptions, Chromium

    dr = Chromium(9250)
    tab = dr.latest_tab
    print(tab.title)
    tab.set.NoneElement_value('未找到')
    tab.get("https://ipp.taobao.com/ippCenter.htm#/complaint/form?platform=taobao")
    time.sleep(3)
    frame = tab.get_frame('x://*[@id="alibaba-login-box"]', timeout=10)
    if frame.attr == '未找到':
        print("已登录")
        if tab.ele('x://*[@class="menu-label"]') is not None:
            cookie = 转换为cookie格式(tab.cookies().as_dict())
            token = 获取token值(tab)
            return cookie, token
        return False
    else:
        print("正在登录")
        账号输入 = frame.ele('x://*[@name="fm-login-id"]')
        密码输入 = frame.ele('x://*[@name="fm-login-password"]')
        账号输入.input(账号)
        密码输入.input(密码)
        登录按钮 = frame.ele('x://*[@type="submit"]')
        登录按钮.click()
        tab.wait.load_start()
        time.sleep(2)
        tab.wait.doc_loaded()
        token = 获取token值(tab)
        cookie = 转换为cookie格式(tab.cookies().as_dict())
        print(cookie)
        return cookie, token


def main(账号, 密码, 间隔, 链接文件, 输出文件名):
    桌面路径 = os.path.join(os.path.expanduser("~"), "Desktop")
    输出文件路径 = os.path.join(桌面路径, 输出文件名)
    os.makedirs(os.path.dirname(输出文件路径), exist_ok=True)

    清除代理()
    cookie, token = 取账号cookie(账号, 密码)
    处理淘宝链接数据(链接文件, 输出文件路径, 间隔, cookie, token)

    print(f"验证完成，结果已保存到: {输出文件路径}")
    return 输出文件路径
