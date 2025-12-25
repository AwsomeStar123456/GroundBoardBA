
import gc
import ssl
import socket

try:
	import uos as os
except Exception:
	import os

try:
	import ujson as json
except Exception:
	import json

try:
	import utime as time
except Exception:
	import time

import utils.jsonsupport as supportjson


RAW_HOST = "raw.githubusercontent.com"
API_HOST = "api.github.com"

# Default repo for updates (used if config.json doesn't provide GITHUB_REPO)
DEFAULT_GITHUB_REPO = "AwsomeStar123456/GroundBoardBA"


def _sleep_ms(ms):
	try:
		time.sleep_ms(ms)
	except Exception:
		time.sleep(ms / 1000.0)


def _wrap_tls(sock, host):
	try:
		return ssl.wrap_socket(sock, server_hostname=host)
	except Exception:
		return ssl.wrap_socket(sock)


def _ensure_dirs_for_file(path):
	if not path or "/" not in path:
		return
	parts = path.split("/")[:-1]
	cur = ""
	for p in parts:
		if not p:
			continue
		cur = p if cur == "" else cur + "/" + p
		try:
			os.mkdir(cur)
		except Exception:
			pass


def _read_headers(sock, max_bytes=4096):
	data = b""
	while len(data) < max_bytes and b"\r\n\r\n" not in data:
		chunk = sock.read(256) if hasattr(sock, "read") else sock.recv(256)
		if not chunk:
			break
		data += chunk
	if b"\r\n\r\n" not in data:
		return None, None
	header, rest = data.split(b"\r\n\r\n", 1)
	return header, rest


def _parse_status_code(header_bytes):
	try:
		first = header_bytes.split(b"\r\n", 1)[0]
		return int(first.split(b" ")[1])
	except Exception:
		return None


def _http_get_stream(host, path, port=443, timeout_s=12, extra_headers=None):
	addr = socket.getaddrinfo(host, port)[0][-1]
	s = socket.socket()
	try:
		try:
			s.settimeout(timeout_s)
		except Exception:
			pass
		s.connect(addr)
		ss = _wrap_tls(s, host)
		try:
			st = getattr(ss, "settimeout", None)
			if st:
				st(timeout_s)
		except Exception:
			pass

		headers = ""
		if extra_headers:
			for k, v in extra_headers.items():
				headers += "{}: {}\r\n".format(k, v)

		# Use HTTP/1.0 to avoid chunked encoding.
		req = (
			"GET {} HTTP/1.0\r\n"
			"Host: {}\r\n"
			"User-Agent: GroundBoardBA\r\n"
			"Accept: */*\r\n"
			"Accept-Encoding: identity\r\n"
			"Connection: close\r\n"
			"{}"
			"\r\n"
		).format(path, host, headers)

		try:
			ss.write(req.encode("utf-8"))
		except Exception:
			ss.send(req.encode("utf-8"))

		return ss, s
	except Exception:
		try:
			s.close()
		except Exception:
			pass
		raise


def _http_get_to_bytes(host, path, timeout_s=12, extra_headers=None, max_bytes=200000):
	ss = None
	s = None
	try:
		ss, s = _http_get_stream(host, path, timeout_s=timeout_s, extra_headers=extra_headers)
		header, rest = _read_headers(ss)
		if header is None:
			return None, None
		code = _parse_status_code(header)
		chunks = []
		size = 0
		if rest:
			chunks.append(rest)
			size += len(rest)
		while True:
			chunk = ss.read(1024) if hasattr(ss, "read") else ss.recv(1024)
			if not chunk:
				break
			chunks.append(chunk)
			size += len(chunk)
			if size > max_bytes:
				raise MemoryError("HTTP body exceeded max_bytes")
		return code, b"".join(chunks)
	finally:
		try:
			if ss:
				ss.close()
		except Exception:
			pass
		try:
			if s:
				s.close()
		except Exception:
			pass


def _http_get_to_file(host, path, dest_path, timeout_s=20, extra_headers=None):
	ss = None
	s = None
	tmp_path = dest_path + ".tmp"
	try:
		_ensure_dirs_for_file(dest_path)
		ss, s = _http_get_stream(host, path, timeout_s=timeout_s, extra_headers=extra_headers)

		header, rest = _read_headers(ss)
		if header is None:
			return False, "no_headers"
		code = _parse_status_code(header)
		if code != 200:
			return False, "http_{}".format(code)

		with open(tmp_path, "wb") as f:
			if rest:
				f.write(rest)
			while True:
				chunk = ss.read(1024) if hasattr(ss, "read") else ss.recv(1024)
				if not chunk:
					break
				f.write(chunk)

		# Replace existing file atomically-ish.
		try:
			os.remove(dest_path)
		except Exception:
			pass
		try:
			os.rename(tmp_path, dest_path)
		except Exception:
			# Fallback: copy then remove tmp
			with open(tmp_path, "rb") as src, open(dest_path, "wb") as out:
				while True:
					buf = src.read(1024)
					if not buf:
						break
					out.write(buf)
			try:
				os.remove(tmp_path)
			except Exception:
				pass

		return True, None

	except Exception as e:
		try:
			os.remove(tmp_path)
		except Exception:
			pass
		return False, str(e)

	finally:
		try:
			if ss:
				ss.close()
		except Exception:
			pass
		try:
			if s:
				s.close()
		except Exception:
			pass


def _normalize_subdir(subdir):
	if not subdir:
		return ""
	subdir = str(subdir).strip().strip("/")
	return subdir


def _join_repo_path(subdir, relpath):
	subdir = _normalize_subdir(subdir)
	relpath = str(relpath).lstrip("/")
	return (subdir + "/" + relpath) if subdir else relpath


def _repo_owner_and_name(repo):
	if not repo:
		return None, None
	# Allow passing a full GitHub URL.
	try:
		repo = str(repo).strip()
		if repo.startswith("https://github.com/"):
			repo = repo[len("https://github.com/") :]
		if repo.endswith(".git"):
			repo = repo[: -len(".git")]
		repo = repo.strip("/")
	except Exception:
		pass
	if "/" not in repo:
		return None, None
	owner, name = repo.split("/", 1)
	owner = owner.strip()
	name = name.strip()
	if not owner or not name:
		return None, None
	return owner, name


def _get_manifest_file_list(repo, branch, subdir, manifest_path):
	full_path = "/{}/{}/{}".format(repo, branch, _join_repo_path(subdir, manifest_path))
	code, body = _http_get_to_bytes(RAW_HOST, full_path, timeout_s=15, max_bytes=60000)
	if code != 200 or not body:
		return None
	try:
		obj = json.loads(body.decode("utf-8"))
	except Exception:
		obj = json.loads(body)

	if isinstance(obj, list):
		return obj
	if isinstance(obj, dict):
		files = obj.get("files")
		if isinstance(files, list):
			return files
	return None


def _get_tree_file_list(repo_owner, repo_name, branch, subdir, allowed_exts):
	# GitHub tree API (public repos): /repos/{owner}/{repo}/git/trees/{branch}?recursive=1
	path = "/repos/{}/{}/git/trees/{}?recursive=1".format(repo_owner, repo_name, branch)
	headers = {"Accept": "application/vnd.github+json"}
	code, body = _http_get_to_bytes(API_HOST, path, timeout_s=20, extra_headers=headers, max_bytes=200000)
	if code != 200 or not body:
		return None
	try:
		obj = json.loads(body.decode("utf-8"))
	except Exception:
		obj = json.loads(body)

	tree = obj.get("tree") if isinstance(obj, dict) else None
	if not tree:
		return None

	subdir = _normalize_subdir(subdir)
	out = []
	for item in tree:
		try:
			if item.get("type") != "blob":
				continue
			p = item.get("path")
			if not p:
				continue
			if subdir:
				if not p.startswith(subdir + "/"):
					continue
				p_rel = p[len(subdir) + 1 :]
			else:
				p_rel = p
			# Only include certain extensions by default.
			if allowed_exts:
				ok = False
				for ext in allowed_exts:
					if p_rel.endswith(ext):
						ok = True
						break
				if not ok:
					continue
			out.append(p_rel)
		except Exception:
			pass

	return out


def run_update(connect_wifi=True):
	"""Download latest project files from GitHub and replace local files.

	Config keys (config.json):
	  - GITHUB_REPO: "owner/repo" (required)
	  - GITHUB_BRANCH: "main" (optional, default "main")
	  - GITHUB_SUBDIR: "MicroPython/GroundBoardBA" (optional)
	  - UPDATE_MANIFEST_PATH: "update_manifest.json" (optional)
	  - UPDATE_FILE_EXTENSIONS: [".py", ".json"] (optional)
	  - UPDATE_PRESERVE_FILES: ["config.json"] (optional)

	Returns (ok: bool, info: dict)
	"""
	repo = supportjson.readFromJSON("GITHUB_REPO") or DEFAULT_GITHUB_REPO
	branch = supportjson.readFromJSON("GITHUB_BRANCH") or "main"
	subdir = supportjson.readFromJSON("GITHUB_SUBDIR") or ""
	manifest_path = supportjson.readFromJSON("UPDATE_MANIFEST_PATH") or "update_manifest.json"

	allowed_exts = supportjson.readFromJSON("UPDATE_FILE_EXTENSIONS")
	if not isinstance(allowed_exts, list):
		allowed_exts = [".py", ".json"]

	preserve = supportjson.readFromJSON("UPDATE_PRESERVE_FILES")
	if not isinstance(preserve, list):
		preserve = ["config.json"]

	if not repo:
		return False, {"reason": "missing_config", "missing": "GITHUB_REPO"}

	owner, name = _repo_owner_and_name(repo)
	if owner is None:
		return False, {"reason": "bad_config", "key": "GITHUB_REPO", "value": repo}

	if connect_wifi:
		try:
			import utils.wifi as WiFi
			WiFi.resetWifi()
			st = WiFi.startupWifi()
			if not st or not st.get("internet_ok"):
				return False, {"reason": "no_internet", "wifi": st}
		except Exception as e:
			return False, {"reason": "wifi_error", "error": str(e)}

	print("Update starting: repo=", repo, "branch=", branch, "subdir=", subdir)

	# Prefer a small manifest file if present (more reliable on low memory).
	files = None
	try:
		files = _get_manifest_file_list(repo, branch, subdir, manifest_path)
		if files:
			print("Using manifest file list:", manifest_path, "count=", len(files))
	except Exception as e:
		print("Manifest fetch failed:", e)

	if not files:
		files = _get_tree_file_list(owner, name, branch, subdir, allowed_exts)
		if not files:
			return False, {"reason": "no_file_list"}
		print("Using GitHub tree file list. count=", len(files))

	# Filter out preserved files.
	preserve_set = set([str(p).lstrip("/") for p in preserve])
	files = [f for f in files if str(f).lstrip("/") not in preserve_set]

	# Update ordering: update libraries/utilities first; main/updates last.
	def _sort_key(p):
		p = str(p)
		if p == "updates.py":
			return (2, p)
		if p == "main.py":
			return (3, p)
		return (1, p)

	files.sort(key=_sort_key)

	ok_count = 0
	fail = []

	for i, relpath in enumerate(files):
		gc.collect()
		relpath = str(relpath).lstrip("/")
		remote_path = "/{}/{}/{}".format(repo, branch, _join_repo_path(subdir, relpath))
		print("[{} / {}] GET".format(i + 1, len(files)), remote_path, "->", relpath)

		ok, err = _http_get_to_file(RAW_HOST, remote_path, relpath, timeout_s=25)
		if ok:
			ok_count += 1
		else:
			fail.append({"file": relpath, "error": err})
			# Stop early if something goes wrong; reduces chance of half-updated state.
			break

		_sleep_ms(50)

	if fail:
		print("Update failed:", fail[0])
		return False, {"reason": "download_failed", "ok": ok_count, "failed": fail}

	print("Update complete. files_updated=", ok_count)
	return True, {"updated": ok_count}

