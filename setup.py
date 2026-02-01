from setuptools import setup, find_packages

pkg_name = "qdp"

def read_file(fname):
    with open(fname, "r") as f:
        return f.read()

requirements = [
    "pathvalidate",
    "requests",
    "mutagen",
    "beautifulsoup4", # 如果你完全不下载 last.fm 链接，这个也能删
    "rich", # 保留 rich 用于美观的进度条
]

setup(
    name=pkg_name,
    version="114.0.0",
    author="lingion",
    description="Minimalist Qobuz Downloader",
    url="https://github.com/Lingion",
    install_requires=requirements,
    entry_points={
        "console_scripts": [
            "qdp = qobuz_dl:main",
        ],
    },
    packages=find_packages(),
    classifiers=[
        "Programming Language :: Python :: 3",
        "Operating System :: OS Independent",
    ],
    python_requires=">=3.6",
)
