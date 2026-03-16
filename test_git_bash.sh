#!/bin/bash
echo "Git Bash测试脚本"
echo "当前目录: $(pwd)"
echo "Bash版本: $BASH_VERSION"
echo "Git版本: $(git --version 2>/dev/null || echo 'Git未找到')"