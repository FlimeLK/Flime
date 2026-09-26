from admin_web.app import app, cfg
import uvicorn


if __name__ == "__main__":
    uvicorn.run(app, host=cfg.host, port=cfg.port)

