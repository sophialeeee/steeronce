from setuptools import setup


setup(
    name="steeronce",
    version="0.3.0",
    description="Teach Codex how you work across sessions, privately",
    url="https://github.com/sophialeeee/steeronce",
    license="MIT",
    python_requires=">=3.9",
    py_modules=["steeronce"],
    package_dir={"": "plugins/steeronce/skills/steeronce/scripts"},
    entry_points={"console_scripts": ["steeronce=steeronce:main"]},
)
