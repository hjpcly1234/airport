#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import time
import json
import random
import requests
from bs4 import BeautifulSoup as bs4
from urllib.parse import urljoin
from concurrent.futures import ThreadPoolExecutor
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ====================== 配置区 ======================
DOMAIN_FILE   = "valid_links2.txt"       
BACKUP_DOMAIN = "https://4567.bno.us.ci" 
RESULT_JSON   = "日韩有码.json"           

START_PAGE    = 1
MAX_PAGE      = 3   # 既然测通了，可以直接恢复到 50 页
MAX_WORKERS   = 3     # 🎯 再次降低并发到 3，避免把对方服务器冲到 500 崩溃
# ====================================================

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Connection": "keep-alive"
})

def fetch(url, is_play_page=False):
    """强力抗高压请求函数：支持超时重试、500/503退避重试、随机延迟"""
    retries = 4  # 🎯 提高重试次数到 4 次
    for i in range(retries):
        try:
            # 🎯 如果是解析播放页，在请求前随机中断 1 ~ 3 秒，错开多线程的并发峰值
            if is_play_page:
                time.sleep(random.uniform(1.0, 3.0))
            elif i > 0:
                time.sleep(3) # 重试期间歇 3 秒
                
            # timeout 设置为 20 秒，给对方多一点响应时间
            r = session.get(url, timeout=20, verify=False)
            
            # 如果对方服务器崩溃(500/502/503)，说明我们冲太快了，打印并等待重试
            if r.status_code in [500, 502, 503, 403]:
                print(f"  ⚠️ 对方服务器返回 {r.status_code}，正在进行第 {i+1}/{retries} 次降频重试...")
                continue
                
            r.raise_for_status()
            r.encoding = r.apparent_encoding or 'utf-8'
            return r
        except (requests.exceptions.RequestException, Exception) as e:
            if i == retries - 1:
                print(f"  ❌ 彻底失败 (已重试 {retries} 次): {url} | 原因: {e}")
            else:
                print(f"  ⚠️ 请求超时或断连，正在尝试第 {i+1}/{retries} 次重试...")
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
        r = fetch(url, is_play_page=False)
        if not r: 
            continue
            
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
        # 列表页每页之间歇息 1.5 秒
        time.sleep(1.5)
        
    print(f"✅ 列表扫描结束，共获得 {len(items)} 条基础记录。")
    return items

def process_single_item(item):
    """多线程解析内容（标记为播放页，激活内部的随机延迟和强力重试）"""
    r = fetch(item["link"], is_play_page=True)
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
    
    if not raw_items:
        print("⚠️ 警告：本次未能捕获到任何有效列表数据。")
        # 如果原本有旧文件，不覆盖它，保护数据
        if not os.path.exists(RESULT_JSON):
            with open(RESULT_JSON, "w", encoding="utf-8") as f:
                json.dump({"zhubo": []}, f, ensure_ascii=False, indent=2)
        return

    print(f"\n⚡ 开启多线程“拟人化缓释”解析...")
    final_zhubo = []
    
    # 采用小并发机制，配合内部的 sleep，让请求像下小雨一样淅淅沥沥地过去，不引起防火墙注意
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        results = pool.map(process_single_item, raw_items)
        for res in results:
            if res:
                final_zhubo.append(res)

    output_data = {"zhubo": final_zhubo}
    with open(RESULT_JSON, "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)
        
    print(f"\n🎉 运行成功！汇总 JSON 已输出，共计有效影片: {len(final_zhubo)}/{len(raw_items)} 条。")

if __name__ == "__main__":
    main()
