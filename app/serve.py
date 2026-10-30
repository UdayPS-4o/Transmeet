"""Entry point used by start.sh: plain HTTP on port 8000 and, with HTTPS=true, HTTPS on
port 8443 as well.

Both listeners live in one process because rooms are kept in memory: with two separate
servers, a laptop on http://localhost:8000 and one on https://<ip>:8443 would end up in
different rooms. The HTTPS listener shares the app and starts once the HTTP one has
loaded the models.
"""
import asyncio
import os

import uvicorn

COMMON = {"host": "0.0.0.0", "proxy_headers": True, "forwarded_allow_ips": "*"}


async def main() -> None:
    http = uvicorn.Server(uvicorn.Config("app.main:app", port=8000, **COMMON))
    servers = [http]
    tasks = [asyncio.create_task(http.serve())]
    if os.getenv("HTTPS", "false").lower() == "true":
        cert_dir = os.getenv("CERT_DIR", "/models/cert")
        while not http.started and not tasks[0].done():     # models load during startup
            await asyncio.sleep(0.2)
        https = uvicorn.Server(uvicorn.Config(
            "app.main:app", port=8443, lifespan="off", **COMMON,
            ssl_keyfile=os.path.join(cert_dir, "key.pem"),
            ssl_certfile=os.path.join(cert_dir, "cert.pem")))
        servers.append(https)
        tasks.append(asyncio.create_task(https.serve()))
    # when one listener stops (Ctrl+C, docker stop), stop the other too
    _, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    for s in servers:
        s.should_exit = True
    await asyncio.gather(*pending, return_exceptions=True)


if __name__ == "__main__":
    asyncio.run(main())
