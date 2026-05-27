#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import time
import json
import requests
from bs4 import BeautifulSoup as bs4
from urllib.parse import urljoin
from concurrent.futures import ThreadPoolExecutor
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ====================== 配置区 ======================
DOMAIN_FILE   = "valid_links2.txt"       
BACKUP_DOMAIN = "https://huangsecangku.net" 
RESULT_JSON   = "日韩有码.json"           

START_PAGE    = 1
MAX_PAGE      = 5     # 先用 5 页进行测试，测通了再改回 50
MAX_WORKERS   = 5     # 降低并发，防止由于请求太快被网站防火墙拉黑
# ====================================================

# 建立全局 Session 保持 Cookie 状态，同时洗白 Header，模仿完全真实的现代浏览器
session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Cache-Control": "max-cache-control",
    "Upgrade-Insecure-Requests": "1"
})

def fetch(url):
    """带高级伪装和状态保持的请求函数"""
    for i in range(3):
        try:
            # 模拟人手停顿，防止频率过快触发风控
            if i > 0:
                time.sleep(2)
            r = session.get(url, timeout=15, verify=False)
            
            # 如果遇到了 403 或 503，说明被 Cloudflare 拦截了，打印出来方便排查
            if r.status_code in [403, 503]:
                print(f"  ⚠️ 触发风控! 状态码: {r.status_code}，正在尝试重试...")
                continue
                
            r.raise_for_status()
            r.encoding = r.apparent_encoding or 'utf-8'
            return r
        except Exception as e:
            print(f"  ⚠️ 请求失败: {e}")
            time.sleep(1)
    return None

def get_latest_domain():
    """获取最新可用域名"""
    try:
        if os.path.exists(DOMAIN_FILE):
            with open(DOMAIN_FILE, "r", encoding="utf-8") as f:
                domains = [l.strip() for l in f if l.strip()]
            if domains:
                last = domains[-1]
                if not last.startswith("http"):
                    last = "http://" + last
                try:
                    r = session.head(last, timeout=5, verify=False)
                    if r.status_code < 400:
                        print(f"使用最新域名: {last}")
                        return last.rstrip("/")
                except:
                    pass
    except:
        pass
    print(f"使用备用域名: {BACKUP_DOMAIN}")
    return BACKUP_DOMAIN.rstrip("/")

def extract_m3u8(html):
    """从 HTML 源码中提取 m3u8 链接"""
    patterns = [
        r'"url"\s*:\s*"([^"]+\.m3u8[^"]*)"',
        r'url\s*=\s*\'([^\']+\.m3u8[^\']*)\'',
        r'url\s*=\s*"([^"]+\.m3u8[^"]*)"',
        r'"link"\s*:\s*"([^"]+\.m3u8[^"]*)"'
    ]
    for pattern in patterns:
        m = re.search(pattern, html)
        if m:
            return m.group(1).replace("\\", "")
    return None

def crawl_list(base_url):
    """抓取列表页"""
    print("🚀 开始抓取分类列表页...")
    items = []
    for page in range(START_PAGE, MAX_PAGE + 1):
        url = f"{base_url}/vodtype/7-{page}.html"
        print(f"  正在扫描第 {page} 页 → {url}")
        r = fetch(url)
        if not r: 
            continue
        
        # 调试输出：如果抓出来的网页太短，说明被拦截了
        if len(r.text) < 2000:
            print(f"  ⚠️ 第 {page} 页返回内容异常过短，疑似遭遇验证阻拦。")
            
        soup = bs4(r.text, "html.parser")
        cards = soup.select("a.stui-vodlist__thumb.lazyload")
        
        for a in cards:
            raw_link = a.get("href") or ""
            link = urljoin(base_url, raw_link)
            
            if "/vodplay/" in link and "?play=" not in link:
                link = link + "?play=1"
            
            title = (a.get("title") or "").strip()
            img = a.get("data-original") or a.get("src") or ""
            if img and not img.startswith("http"):
                img = urljoin(base_url, img)
            
            if title and "/vodplay/" in link and "bh.html" not in link:
                items.append({
                    "title": re.sub(r'\s+', ' ', title.replace("_", " ")).strip(),
                    "link": link,
                    "img": img
                })
        time.sleep(1) # 每页之间歇息1秒，保持礼貌
        
    print(f"✅ 列表扫描结束，共获得 {len(items)} 条基础记录。")
    return items

def process_single_item(item):
    """多线程解析内容"""
    r = fetch(item["link"])
    m3u8_url = extract_m3u8(r.text) if r else None
    
    if m3u8_url:
        print(f" 成功解析 → {item['title']}")
        return {
            "address": m3u8_url,
            "img": item["img"],
            "title": item["title"]
        }
    else:
        return None

def main():
    base_url = get_latest_domain()
    raw_items = crawl_list(base_url)
    
    # 🎯 防崩溃兜底：就算真的抓到0条，也强行生成一个空的 JSON 文件，防止后续 Git 报错卡死
    if not raw_items:
        print("⚠️ 警告：本次未能捕获到任何有效数据。已生成空兜底结构。")
        with open(RESULT_JSON, "w", encoding="utf-8") as f:
            json.dump({"zhubo": []}, f, ensure_ascii=False, indent=2)
        return

    print(f"\n⚡ 开启多线程内存解析...")
    final_zhubo = []
    
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        results = pool.map(process_single_item, raw_items)
        for res in results:
            if res:
                final_zhubo.append(res)

    output_data = {"zhubo": final_zhubo}
    with open(RESULT_JSON, "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)
        
    print(f"\n🎉 运行成功！汇总 JSON 已输出，共计有效影片: {len(final_zhubo)} 条。")

if __name__ == "__main__":
    main()
