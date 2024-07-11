"""
Install pychemauth.

author: nam
"""
from setuptools import find_packages, setup

# Get __version__ from __init__ file
exec(open("pychemauth/__init__.py").read())

setup(
    name="pychemauth",
    description="Python-based Chemometric Authentication",
    author="Nathan A. Mahynski",
    homepage="https://github.com/mahynski/pychemauth",
    python_requires=">=3.9.0",
    version=__version__,
    packages=find_packages(),
    license_files=("LICENSE",),
    test_suite="tests",
    tests_require=["pytest"],
    classifiers=[
        "Intended Audience :: Science/Research",
        "Operating System :: POSIX :: Linux",
    ],
    install_requires=[
        "baycomp==1.0.3",
        "bokeh",
        "BorutaShap @ git+https://github.com/Ekeany/Boruta-Shap.git@38af879",
        "imbalanced-learn==0.11.0",
        "IPython",
        "ipywidgets",
        "matplotlib==3.8.4",
        "nodejs==0.1.1",
        "numpy==1.26.4",
        "pandas==2.2.1",
        "pre-commit==3.3.3",
        "scikit-learn==1.4.2",
        "scipy==1.13.0",
        "seaborn==0.13.2",
        "shap==0.45.1",
        "tqdm==4.66.2",
        "umap-learn==0.5.3",
        "watermark==2.4.3",
        "pytest==7.4.0",
        "xgboost==2.0.3",
        "missingno==0.5.2",
        "huggingface_hub==0.23.4",
    ],
)
