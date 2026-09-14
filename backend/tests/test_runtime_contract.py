from pathlib import Path


def test_requirements_pin_onnx_runtime_and_exclude_paddlepaddle():
    requirements = (
        Path(__file__).resolve().parents[1] / "requirements.txt"
    ).read_text(encoding="utf-8").lower().splitlines()

    assert "onnxruntime==1.29.0" in requirements
    assert "paddleocr==3.7.0" in requirements
    assert "paddlex[ocr-core]==3.7.2" in requirements
    assert not any(line.startswith("paddlepaddle") for line in requirements)


def test_pyproject_declares_runtime_and_dev_dependencies_for_hosted_install():
    import tomllib

    backend_root = Path(__file__).resolve().parents[1]
    pyproject = tomllib.loads(
        (backend_root / "pyproject.toml").read_text(encoding="utf-8")
    )
    requirements = {
        line.strip().lower()
        for line in (backend_root / "requirements.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }

    runtime = {item.lower() for item in pyproject["project"]["dependencies"]}
    dev = {
        item.lower()
        for item in pyproject["project"]["optional-dependencies"]["dev"]
    }

    assert runtime | dev == requirements
    assert "fastapi==0.116.1" in runtime
    assert pyproject["tool"]["vercel"]["entrypoint"] == "app.main:app"
