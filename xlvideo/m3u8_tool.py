import re
import requests
from urllib.parse import urljoin, urlparse
from playwright.async_api import async_playwright
import json
import random


class M3U8Parser:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })

    def extract_title_from_html(self, html_content):
        """从HTML中提取标题"""
        title_patterns = [
            r'<title[^>]*>(.*?)</title>',
            r'<h1[^>]*>(.*?)</h1>',
            r'<meta[^>]*property=["\']og:title["\'][^>]*content=["\']([^"\']*)["\']',
            r'<meta[^>]*name=["\']title["\'][^>]*content=["\']([^"\']*)["\']',
            r'<meta[^>]*name=["\']twitter:title["\'][^>]*content=["\']([^"\']*)["\']',
            r'<h2[^>]*>(.*?)</h2>',
            r'<h3[^>]*>(.*?)</h3>',
        ]

        for pattern in title_patterns:
            match = re.search(pattern, html_content, re.IGNORECASE | re.DOTALL)
            if match:
                title = match.group(1).strip()
                # 清理HTML标签
                title = re.sub(r'<[^>]+>', '', title)
                # 清理多余的空白字符
                title = re.sub(r'\s+', ' ', title).strip()
                if title:
                    return title

        return "未知标题"

    def extract_m3u8_links_from_text(self, text, base_url):
        """从文本中提取m3u8链接"""
        # 匹配各种m3u8链接模式
        patterns = [
            r'(?:src|source|file|url)["\']?\s*[:=]\s*["\']?([^"\'>\s]+\.m3u8)',
            r'(?:src|source|file|url)["\']?\s*[:=]\s*["\']?([^"\'>\s]+\.m3u8[^"\'>\s]*)',
            r'"([^"]*\.m3u8)"',
            r"'([^']*\.m3u8)'",
            r'(?:video|player).*?(?:src|source|file|url)["\']?\s*[:=]\s*["\']?([^"\'>\s]+\.m3u8[^"\'>\s]*)',
        ]

        links = set()
        for pattern in patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for match in matches:
                full_url = urljoin(base_url, match.strip())
                if self.is_valid_m3u8_url(full_url):
                    links.add(full_url)

        # 尝试匹配嵌入在JavaScript中的链接
        js_matches = re.findall(r'[\'"]([^\'"]*\.m3u8)[\'"]', text)
        for match in js_matches:
            full_url = urljoin(base_url, match.strip())
            if self.is_valid_m3u8_url(full_url):
                links.add(full_url)

        # 尝试匹配JSON配置中的链接
        json_patterns = [
            r'({.*?"(?:src|source|file|url)".*?"[^"]*\.m3u8"[^}]*})',
            r'({.*?"(?:playlist|sources?)".*?"[^"]*\.m3u8"[^}]*})'
        ]
        for pattern in json_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE | re.DOTALL)
            for match in matches:
                try:
                    # 尝试解析为JSON
                    data = json.loads(match)
                    urls = self.extract_urls_from_json(data)
                    for url in urls:
                        full_url = urljoin(base_url, url)
                        if self.is_valid_m3u8_url(full_url):
                            links.add(full_url)
                except:
                    continue

        return list(links)

    def extract_urls_from_json(self, obj):
        """从JSON对象中递归提取URL"""
        urls = []
        if isinstance(obj, dict):
            for key, value in obj.items():
                if key.lower() in ['src', 'source', 'file', 'url', 'srcset'] and isinstance(value,
                                                                                            str) and value.endswith(
                    '.m3u8'):
                    urls.append(value)
                elif isinstance(value, (dict, list)):
                    urls.extend(self.extract_urls_from_json(value))
        elif isinstance(obj, list):
            for item in obj:
                urls.extend(self.extract_urls_from_json(item))
        return urls

    def is_valid_m3u8_url(self, url):
        """验证URL是否为有效的m3u8链接"""
        try:
            parsed = urlparse(url)
            return bool(parsed.netloc) and url.lower().endswith('.m3u8')
        except Exception:
            return False

    def fetch_page_content(self, url):
        """使用requests获取页面内容"""
        try:
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            return response.text
        except Exception as e:
            print(f"Error fetching page with requests: {e}")
            return None

    async def fetch_with_playwright_intercept(self, url):
        """使用Playwright拦截网络请求获取m3u8链接"""
        m3u8_links = []
        browser = None
        page = None
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
                )
                page = await context.new_page()

                # 拦截所有网络响应 - 使用同步方式避免异步问题
                def handle_response(response):
                    try:
                        response_url = response.url
                        content_type = response.headers.get('content-type', '')

                        # 检查是否是m3u8文件
                        if '.m3u8' in response_url.lower() or 'mpegurl' in content_type.lower():
                            print(f"从网络请求中发现m3u8: {response_url}")
                            if response_url not in m3u8_links:
                                m3u8_links.append(response_url)

                        # 对于小响应，同步检查内容（不等待text）
                        # 注意：这里只做URL匹配，详细内容检查在下面单独处理
                    except Exception as e:
                        # 忽略浏览器关闭时的异常
                        if 'Target closed' not in str(e) and 'Browser has been closed' not in str(e):
                            pass

                # 注册响应拦截器（同步回调）
                page.on("response", handle_response)

                # 访问页面，使用domcontentloaded而非networkidle避免超时
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    # 等待一段时间让AJAX请求完成
                    await page.wait_for_timeout(5000)
                except Exception as e:
                    print(f"页面加载超时或失败: {e}")
                    # 即使超时，也尝试获取已加载的内容和捕获的链接
                    pass

                # 获取页面内容用于提取标题
                content = None
                try:
                    content = await page.content()
                except:
                    pass

                # 额外检查：遍历已捕获的链接，验证是否为有效的m3u8
                valid_links = []
                for link in m3u8_links:
                    try:
                        # 快速验证链接
                        resp = self.session.head(link, timeout=3)
                        if resp.status_code == 200:
                            valid_links.append(link)
                        else:
                            # HEAD失败，尝试GET前几个字节
                            resp = self.session.get(link, timeout=3, headers={'Range': 'bytes=0-199'})
                            if '#EXTM3U' in resp.text[:100]:
                                valid_links.append(link)
                    except:
                        # 无法验证的链接也保留，可能是需要特定header
                        valid_links.append(link)

                return content, valid_links
        except Exception as e:
            print(f"Error fetching page with Playwright interception: {e}")
            return None, []
        finally:
            # 确保浏览器正确关闭
            if page:
                try:
                    await page.close()
                except:
                    pass
            if browser:
                try:
                    await browser.close()
                except:
                    pass

    def find_direct_m3u8_in_response(self, response_text, base_url):
        """尝试在响应中直接查找m3u8文件内容"""
        # 检查响应是否本身就是m3u8内容
        if '#EXTM3U' in response_text[:100]:
            return [(base_url, "Direct M3U8 File")]
        return []

    async def parse_m3u8_links(self, url):
        """解析m3u8链接和标题的主要方法"""
        print(f"开始解析: {url}")

        # 首先尝试直接访问URL看是否是m3u8文件
        try:
            direct_response = self.session.get(url, timeout=10)
            if direct_response.status_code == 200 and '#EXTM3U' in direct_response.text[:100]:
                print("检测到直接的m3u8文件")
                title = self.extract_title_from_html(
                    direct_response.text) if direct_response.text else "Direct M3U8 File"
                return [(url, title)]
        except:
            pass

        # 第一步：使用requests爬取页面HTML
        content = self.fetch_page_content(url)
        results = []

        if content:
            print("使用requests成功获取页面内容")

            # 提取标题
            title = self.extract_title_from_html(content)

            # 从页面HTML中提取m3u8链接
            m3u8_links = self.extract_m3u8_links_from_text(content, url)

            # 如果找到了链接，则随机返回一个
            if m3u8_links:
                print(f"从页面HTML中找到 {len(m3u8_links)} 个m3u8链接")
                selected_link = random.choice(m3u8_links)
                print(f"随机选择: {selected_link}")
                results.append((selected_link, title))
                return results

            # 检查是否是直接的m3u8内容
            direct_links = self.find_direct_m3u8_in_response(content, url)
            if direct_links:
                return direct_links

        # 第二步：如果页面HTML中没找到，使用Playwright拦截网络请求
        print("页面HTML中未找到m3u8链接，尝试拦截网络请求...")
        content, network_m3u8_links = await self.fetch_with_playwright_intercept(url)

        if network_m3u8_links:
            # 如果有页面内容，提取标题；否则使用默认标题
            if content:
                title = self.extract_title_from_html(content)
            else:
                title = "Network Intercepted Video"

            # 随机选择一个链接返回
            selected_link = random.choice(network_m3u8_links)
            results.append((selected_link, title))
            return results
        elif content:
            # Playwright获取了页面但没有找到m3u8
            print("Playwright也未找到m3u8链接")
        else:
            print("Playwright获取页面失败")

        return []

