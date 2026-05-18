import uvicorn

from backend.settings import load_settings


def main() -> None:
    settings = load_settings()
    uvicorn.run("backend.app:app", host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
