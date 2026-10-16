from http.cookiejar import CookieJar
import json
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, Request, build_opener


class Client:
    def __init__(self, url):
        self.url = url
        self.cookies = CookieJar()
        self.opener = build_opener(HTTPCookieProcessor(self.cookies))
        self.csrf = ""
        self.last_headers = None

    def request(self, path="/api/state", payload=None, method=None, csrf=True):
        data = None if payload is None else json.dumps(payload).encode()
        headers = {"Content-Type": "application/json"}
        if csrf:
            headers["X-CSRF-Token"] = self.csrf
        request = Request(self.url + path, data=data, method=method or ("GET" if data is None else "PUT"), headers=headers)
        try:
            response = self.opener.open(request, timeout=3)
        except HTTPError as error:
            response = error
        with response:
            self.last_headers = response.headers
            return response.status, response.read()

    def login(self, username, password="test password"):
        status, body = self.request("/api/session")
        if status != 200:
            raise AssertionError(body)
        self.csrf = json.loads(body)["csrfToken"]
        status, body = self.request("/api/login", {"username": username, "password": password}, method="POST")
        if status != 200:
            raise AssertionError(body)
        _, body = self.request("/api/session")
        self.csrf = json.loads(body)["csrfToken"]
