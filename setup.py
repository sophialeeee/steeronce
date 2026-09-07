from setuptools import setup


setup(
    name="correction-kit",
    version="0.1.0",
    description="Private correction metrics for Codex",
    url="https://github.com/sophialeeee/correction-kit",
    license="MIT",
    python_requires=">=3.9",
    py_modules=["correction_kit"],
    package_dir={"": "plugins/correction-kit/skills/correction-kit/scripts"},
    entry_points={"console_scripts": ["correction-kit=correction_kit:main"]},
)
