#!/usr/bin/env python3
"""
代理连接测试脚本
验证代理服务器是否正常工作
"""

import requests
import os

def test_proxy_connection():
    """测试代理连接"""
    print("🔍 测试代理连接...")
    
    proxy_url = "http://127.0.0.1:7890"
    test_urls = [
        "https://huggingface.co",
        "https://www.google.com",
        "https://api.github.com"
    ]
    
    print(f"使用代理: {proxy_url}")
    print("=" * 60)
    
    for url in test_urls:
        print(f"测试: {url}")
        
        try:
            # 使用代理
            proxies = {
                "http": proxy_url,
                "https": proxy_url
            }
            
            response = requests.get(url, proxies=proxies, timeout=10)
            print(f"✅ 成功! 状态码: {response.status_code}")
            
        except Exception as e:
            print(f"❌ 失败: {e}")
        
        print("-" * 40)

def test_direct_connection():
    """测试直接连接"""
    print("\n🌐 测试直接连接...")
    
    test_urls = [
        "https://huggingface.co",
        "https://www.google.com"
    ]
    
    print("=" * 60)
    
    for url in test_urls:
        print(f"测试: {url}")
        
        try:
            response = requests.get(url, timeout=10)
            print(f"✅ 成功! 状态码: {response.status_code}")
            
        except Exception as e:
            print(f"❌ 失败: {e}")
        
        print("-" * 40)

def main():
    """主函数"""
    print("=" * 60)
    print("🔗 代理连接测试")
    print("=" * 60)
    
    # 测试代理连接
    test_proxy_connection()
    
    # 测试直接连接
    test_direct_connection()
    
    print("\n" + "=" * 60)
    print("测试完成!")
    print("📝 结论:")
    print("   - 如果代理和直接连接都失败: 网络问题")
    print("   - 如果只有代理失败: 代理配置问题")
    print("   - 如果只有直接连接失败: 需要使用代理")

if __name__ == "__main__":
    main()