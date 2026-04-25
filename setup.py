from setuptools import find_packages, setup

pkg_name = "qdp"

requirements = [
    "pathvalidate",
    "requests",
    "mutagen",
    "beautifulsoup4",
    "colorama",
    "rich",
]

setup(
    name=pkg_name,
    version="1.7.2",
    author="lingion",
    description="Local Qobuz web player and toolkit",
    url="https://github.com/Lingion",
    install_requires=requirements,
    entry_points={
        "console_scripts": [
            "qdp = qdp.cli:main",
        ],
    },
    packages=find_packages(),
    classifiers=[
        "Programming Language :: Python :: 3",
        "Operating System :: OS Independent",
    ],
    python_requires=">=3.9",
)
