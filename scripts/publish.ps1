<#
.SYNOPSIS
    构建、校验并发布 Python 项目到 PyPI 或 TestPyPI。

.DESCRIPTION
    通过 pyproject.toml 配置的 PEP 517 构建后端生成 wheel 和源码包。
    构建后端会自动构建 Vue 前端并将静态资源写入 Python 包，最后使用
    Twine 校验产物。
    只有显式传入 -Upload 时才会上传，默认上传到 TestPyPI。

.EXAMPLE
    .\scripts\publish.ps1
    构建并校验发布产物，不上传。

.EXAMPLE
    .\scripts\publish.ps1 -Upload
    构建、校验并上传到 TestPyPI。

.EXAMPLE
    $env:TWINE_USERNAME = "__token__"
    $env:TWINE_PASSWORD = "pypi-xxxxxxxx"
    .\scripts\publish.ps1 -Upload -Repository pypi -NonInteractive
    以非交互方式上传到正式 PyPI。

.NOTES
    构建环境需要 Node.js 18+。首次使用前请安装 Python 发布工具：
    python -m pip install --upgrade build twine
#>
[CmdletBinding()]
param(
    [ValidateSet("pypi", "testpypi")]
    [string]$Repository = "testpypi",

    [switch]$Upload,

    [switch]$NonInteractive,

    [switch]$SkipClean,

    [string]$Python = "python"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Invoke-CheckedCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Command,

        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "命令执行失败（退出码：$LASTEXITCODE）：$Command $($Arguments -join ' ')"
    }
}

function Test-PackageVersionExists {
    param(
        [Parameter(Mandatory = $true)]
        [string]$PythonCommand,

        [Parameter(Mandatory = $true)]
        [string]$ProjectConfigPath,

        [Parameter(Mandatory = $true)]
        [string]$RepositoryName
    )

    $checkCode = @'
import json
import sys
import tomllib
import urllib.error
import urllib.request
from pathlib import Path

pyproject_path = Path(sys.argv[1])
repository = sys.argv[2]
project = tomllib.loads(pyproject_path.read_text(encoding='utf-8'))['project']
package_name = project['name']
package_version = project['version']
host = 'pypi.org' if repository == 'pypi' else 'test.pypi.org'
url = f'https://{host}/pypi/{package_name}/{package_version}/json'

try:
    with urllib.request.urlopen(url, timeout=15) as response:
        json.load(response)
except urllib.error.HTTPError as exc:
    if exc.code == 404:
        print('false')
    else:
        raise
else:
    print('true')
'@

    $result = & $PythonCommand -c $checkCode $ProjectConfigPath $RepositoryName
    if ($LASTEXITCODE -ne 0) {
        throw "检查 PyPI 版本是否存在时失败。"
    }
    return $result.Trim() -eq "true"
}

$projectRoot = Split-Path -Parent $PSScriptRoot
$pyprojectPath = Join-Path $projectRoot "pyproject.toml"
$distPath = Join-Path $projectRoot "dist"
$buildPath = Join-Path $projectRoot "build"

if (-not (Test-Path -LiteralPath $pyprojectPath -PathType Leaf)) {
    throw "未找到项目配置文件：$pyprojectPath"
}

Push-Location $projectRoot
try {
    Write-Host "[1/4] 检查 Python 和发布工具……" -ForegroundColor Cyan
    Invoke-CheckedCommand -Command $Python -Arguments @("--version")

    $missingTools = & $Python -c @'
import importlib.metadata

installed = {
    distribution.metadata['Name'].lower()
    for distribution in importlib.metadata.distributions()
    if distribution.metadata['Name']
}
print(', '.join(name for name in ('build', 'twine') if name not in installed))
'@
    if ($LASTEXITCODE -ne 0) {
        throw "检查 Python 发布工具失败。"
    }
    if (-not [string]::IsNullOrWhiteSpace($missingTools)) {
        throw "缺少发布工具：$missingTools。请先运行：$Python -m pip install --upgrade build twine"
    }

    if (-not $SkipClean) {
        Write-Host "[2/4] 清理旧的构建产物……" -ForegroundColor Cyan
        if (Test-Path -LiteralPath $distPath) {
            Remove-Item -LiteralPath $distPath -Recurse -Force
        }
        if (Test-Path -LiteralPath $buildPath) {
            Remove-Item -LiteralPath $buildPath -Recurse -Force
        }
    }
    else {
        Write-Host "[2/4] 已跳过旧产物清理。" -ForegroundColor Yellow
    }

    Write-Host "[3/4] 使用 pyproject.toml 构建前后端发布包……" -ForegroundColor Cyan
    Invoke-CheckedCommand -Command $Python -Arguments @("-m", "build", "--outdir", $distPath)

    $artifacts = @(
        Get-ChildItem -LiteralPath $distPath -File |
            Where-Object { $_.Name -like "*.whl" -or $_.Name -like "*.tar.gz" }
    )
    if ($artifacts.Count -eq 0) {
        throw "构建完成，但 dist 目录中没有找到 wheel 或源码包。"
    }

    Write-Host "[4/4] 校验发布产物及前端资源……" -ForegroundColor Cyan
    $artifactPaths = @($artifacts | ForEach-Object { $_.FullName })
    Invoke-CheckedCommand -Command $Python -Arguments (@("-m", "twine", "check") + $artifactPaths)

    $wheelArtifact = $artifacts |
        Where-Object { $_.Name -like "*.whl" } |
        Select-Object -First 1
    if ($null -eq $wheelArtifact) {
        throw "构建完成，但没有找到 wheel 产物。"
    }
    $checkStaticCode = @"
import sys
import zipfile

with zipfile.ZipFile(sys.argv[1]) as wheel:
    names = wheel.namelist()
    required_files = {
        'ssw/.env.dev',
        'ssw/default_workspace/mcp.json',
        'ssw/default_workspace/skills/main/skill-creator/SKILL.md',
        'ssw/langgraph.json',
        'ssw/static/index.html',
    }
    missing_files = sorted(required_files.difference(names))
    if missing_files:
        raise SystemExit('wheel 中缺少运行资源：' + ', '.join(missing_files))

    entry_point_files = [
        name for name in names if name.endswith('.dist-info/entry_points.txt')
    ]
    if len(entry_point_files) != 1:
        raise SystemExit('wheel 中缺少唯一的命令入口配置')
    entry_points = wheel.read(entry_point_files[0]).decode('utf-8')
    if 'ssw-agent = ssw.start_web:main' not in entry_points:
        raise SystemExit('wheel 中缺少 ssw-agent 命令入口')

    start_web = wheel.read('ssw/start_web.py').decode('utf-8')
    expected_runtime_root = 'PROJECT_ROOT = Path(__file__).resolve().parent'
    if expected_runtime_root not in start_web:
        raise SystemExit('wheel 中的 start_web.py 未转换为包内资源路径')

    langgraph_config = wheel.read('ssw/langgraph.json').decode('utf-8')
    if '"ssw-agent"' not in langgraph_config:
        raise SystemExit('wheel 中的 LangGraph 配置未声明 ssw-agent 依赖')

    package_env = wheel.read('ssw/.env.dev').decode('utf-8').strip()
    if package_env != 'SSW_WORKSPACE=.ssw':
        raise SystemExit('wheel 中的 .env.dev 未正确配置 SSW_WORKSPACE')
"@
    Invoke-CheckedCommand -Command $Python -Arguments @(
        "-c",
        $checkStaticCode,
        $wheelArtifact.FullName
    )

    Write-Host "构建和校验成功：" -ForegroundColor Green
    $artifacts | ForEach-Object { Write-Host "  - $($_.FullName)" }

    if (-not $Upload) {
        Write-Host "未指定 -Upload，已跳过上传。" -ForegroundColor Yellow
        Write-Host "上传到正式 PyPI：.\scripts\publish.ps1 -Upload -Repository pypi"
        return
    }

    if ($Repository -eq "pypi") {
        Write-Host "即将上传到正式 PyPI。" -ForegroundColor Yellow
    }
    else {
        Write-Host "即将上传到 TestPyPI。" -ForegroundColor Cyan
    }

    if (Test-PackageVersionExists `
        -PythonCommand $Python `
        -ProjectConfigPath $pyprojectPath `
        -RepositoryName $Repository) {
        throw "当前版本已存在于 $Repository，PyPI 不允许覆盖已发布文件。请先更新 pyproject.toml 中的版本号并重新构建。"
    }

    $uploadArguments = @(
        "-m",
        "twine",
        "upload",
        "--verbose",
        "--repository",
        $Repository
    )
    if ($NonInteractive) {
        if ([string]::IsNullOrWhiteSpace($env:TWINE_USERNAME) -or
            [string]::IsNullOrWhiteSpace($env:TWINE_PASSWORD)) {
            throw "非交互上传需要设置 TWINE_USERNAME 和 TWINE_PASSWORD 环境变量。"
        }
        $uploadArguments += "--non-interactive"
    }
    $uploadArguments += $artifactPaths

    Invoke-CheckedCommand -Command $Python -Arguments $uploadArguments
    Write-Host "发布成功，目标仓库：$Repository" -ForegroundColor Green
}
finally {
    Pop-Location
}
