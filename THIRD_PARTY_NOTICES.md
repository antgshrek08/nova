# Third-party software

Nova is built on the open-source work below. Each package keeps its own license; the full
license texts ship with the packages themselves (in the Python environment and `node_modules`).
This list covers what the installers include. It was generated from the build environment and
can lag behind a dependency update.

## Not included in Nova's installers

These are optional and only installed if a user chooses to, on their own computer:

| Package | License | Why it isn't bundled |
|---|---|---|
| piper-tts (offline voice engine) | GPL-3.0-or-later | copyleft license |
| "Ryan" voice model (RyanSpeech) | CC BY-NC-SA 4.0 | non-commercial only |
| pykakasi (Japanese text in voice cloning) | GPL-3.0-or-later | copyleft license |
| MouseInfo, PyMsgBox (unused parts of PyAutoGUI) | GPL-3.0 | copyleft license |

Models downloaded at runtime (the Vosk wake-word model, Apache-2.0; local AI models you pick in
Ollama or LM Studio) are covered by their own licenses.

## Python packages (281)

| Package | Version | License |
|---|---|---|
| aiofile | 3.12.3 | Apache-2.0 |
| aiofiles | 24.1.0 | Apache Software License |
| aiohappyeyeballs | 2.7.1 | Python Software Foundation License |
| aiohttp | 3.14.3 | Apache-2.0 AND MIT |
| aiosignal | 1.4.0 | Apache Software License |
| aiosqlite | 0.22.1 | MIT License |
| annotated-doc | 0.0.5 | MIT |
| annotated-types | 0.8.0 | MIT |
| antlr4-python3-runtime | 4.9.3 | BSD |
| anyio | 4.14.2 | MIT |
| attrs | 26.1.0 | MIT |
| audioop-lts | 0.2.2 | PSF-2.0 |
| audioread | 3.1.0 | MIT |
| Authlib | 1.8.0 | BSD License |
| av | 18.1.0 | BSD-3-Clause |
| bcrypt | 5.0.0 | Apache Software License |
| beartype | 0.22.9 | MIT License |
| boto3 | 1.42.89 | Apache-2.0 |
| botocore | 1.42.97 | Apache-2.0 |
| brotli | 1.2.0 | MIT |
| build | 1.6.0 | MIT |
| cachetools | 7.1.8 | MIT |
| caio | 0.12.2 | Apache-2.0 |
| catalogue | 2.0.10 | MIT License |
| certifi | 2026.7.22 | Mozilla Public License 2.0 (MPL 2.0) |
| cffi | 2.1.1 | MIT-0 |
| cfgv | 3.5.0 | MIT |
| charset-normalizer | 3.5.1 | MIT |
| chatterbox-tts | 0.1.7 | MIT License |
| chromadb | 1.5.9 | Apache Software License |
| click | 8.5.0 | BSD-3-Clause |
| colorama | 0.4.6 | BSD License |
| comtypes | 1.4.11 | MIT License |
| conformer | 0.3.2 | MIT License |
| cryptography | 50.0.1 | Apache-2.0 OR BSD-3-Clause |
| ctranslate2 | 4.8.2 | MIT |
| cyclopts | 4.23.3 | Apache-2.0 |
| decorator | 5.3.1 | BSD-2-Clause |
| defusedxml | 0.7.1 | Python Software Foundation License |
| Deprecated | 1.3.1 | MIT License |
| diffusers | 0.29.0 | Apache Software License |
| distlib | 0.4.3 | Python Software Foundation License |
| distro | 1.9.0 | Apache Software License |
| dnspython | 2.8.0 | ISC License (ISCL) |
| docstring_parser | 0.18.0 | MIT License |
| durationpy | 0.11 | MIT |
| edge-tts | 7.2.8 | GNU Lesser General Public License v3 (LGPLv3) |
| einops | 0.8.2 | MIT License |
| email-validator | 2.3.0 | The Unlicense (Unlicense) |
| exceptiongroup | 1.3.1 | MIT License |
| fastapi | 0.141.1 | MIT |
| faster-whisper | 1.2.1 | MIT License |
| fastmcp | 4.0.1 | Apache-2.0 |
| fastmcp-slim | 4.0.1 | Apache-2.0 |
| fastuuid | 0.14.0 | BSD License |
| ffmpy | 1.0.0 | MIT |
| filelock | 3.32.4 | MIT |
| flatbuffers | 25.12.19 | Apache Software License |
| frozenlist | 1.8.0 | Apache-2.0 |
| fsspec | 2026.7.0 | BSD-3-Clause |
| google-api-core | 2.34.0 | Apache Software License |
| google-api-python-client | 2.200.0 | Apache Software License |
| google-auth | 2.57.0 | Apache Software License |
| google-auth-httplib2 | 0.4.2 | Apache Software License |
| google-auth-oauthlib | 1.4.1 | Apache Software License |
| googleapis-common-protos | 1.75.2 | Apache Software License |
| gradio | 6.8.0 | Apache-2.0 |
| gradio_client | 2.2.0 | Apache-2.0 |
| graphifyy | 0.9.56 | Apache-2.0 |
| greenlet | 3.5.5 | MIT AND PSF-2.0 |
| griffelib | 2.2.0 | ISC |
| groovy | 0.1.2 | MIT License |
| grpcio | 1.83.1 | Apache-2.0 |
| h11 | 0.16.0 | MIT License |
| hf-xet | 1.6.0 | Apache-2.0 |
| http_ece | 1.2.1 | MIT License |
| httpcore | 1.0.9 | BSD-3-Clause |
| httpcore2 | 2.12.0 | BSD-3-Clause |
| httplib2 | 0.32.0 | MIT License |
| httptools | 0.8.0 | MIT |
| httpx | 0.28.1 | BSD License |
| httpx2 | 2.12.0 | BSD-3-Clause |
| huggingface_hub | 1.29.0 | Apache Software License |
| icalendar | 6.3.2 | BSD-2-Clause |
| identify | 2.6.19 | MIT |
| idna | 3.19 | BSD-3-Clause |
| importlib_metadata | 8.9.0 | Apache-2.0 |
| importlib_resources | 7.1.0 | Apache-2.0 |
| iniconfig | 2.3.0 | MIT |
| jaconv | 0.5.0 | MIT License |
| jaraco.classes | 3.4.0 | MIT License |
| jaraco.context | 6.1.2 | MIT |
| jaraco.functools | 4.6.0 | MIT |
| Jinja2 | 3.1.6 | BSD License |
| jiter | 0.16.0 | MIT |
| jmespath | 1.1.0 | MIT License |
| joblib | 1.5.3 | BSD-3-Clause |
| joserfc | 1.7.5 | BSD License |
| jsonref | 1.1.0 | MIT |
| jsonschema | 4.26.0 | MIT |
| jsonschema-path | 0.5.0 | Apache Software License |
| jsonschema-specifications | 2025.9.1 | MIT |
| keyring | 25.7.0 | MIT |
| kubernetes | 36.0.3 | Apache Software License |
| lazy-loader | 0.5 | BSD-3-Clause |
| librosa | 0.11.0 | ISC License (ISCL) |
| litellm | 1.98.0 | MIT |
| llvmlite | 0.49.0 | BSD-2-Clause AND Apache-2.0 WITH LLVM-exception |
| markdown-it-py | 4.2.0 | MIT License |
| MarkupSafe | 3.0.3 | BSD-3-Clause |
| mcp | 2.1.1 | MIT License |
| mcp-types | 2.1.1 | MIT License |
| mdurl | 0.1.2 | MIT License |
| ml_dtypes | 0.6.0 | Apache-2.0 |
| mmh3 | 5.3.0 | MIT License |
| more-itertools | 11.1.0 | MIT |
| mpmath | 1.3.0 | BSD License |
| msgpack | 1.2.2 | Apache-2.0 |
| mss | 10.2.0 | MIT License |
| multidict | 6.7.1 | Apache License 2.0 |
| narwhals | 2.25.0 | MIT |
| networkx | 3.6.1 | BSD-3-Clause |
| nodeenv | 1.10.0 | BSD License |
| numba | 0.67.0 | BSD License |
| numpy | 2.5.2 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 |
| oauthlib | 3.3.1 | BSD-3-Clause |
| omegaconf | 2.3.1 | BSD License |
| onnx | 1.22.0 | Apache-2.0 |
| onnxruntime | 1.29.0 | MIT License |
| openai | 2.54.0 | Apache Software License |
| openapi-pydantic | 0.5.1 | MIT License |
| opencv-python-headless | 5.0.0.93 | Apache Software License |
| opentelemetry-api | 1.44.0 | Apache-2.0 |
| opentelemetry-exporter-otlp-proto-common | 1.44.0 | Apache-2.0 |
| opentelemetry-exporter-otlp-proto-grpc | 1.44.0 | Apache-2.0 |
| opentelemetry-proto | 1.44.0 | Apache-2.0 |
| opentelemetry-sdk | 1.44.0 | Apache-2.0 |
| opentelemetry-semantic-conventions | 0.65b0 | Apache-2.0 |
| openwakeword | 0.6.0 | Apache Software License |
| orjson | 3.12.0 | MPL-2.0 AND (Apache-2.0 OR MIT) |
| overrides | 7.7.0 | Apache License, Version 2.0 |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause |
| pandas | 3.0.5 | BSD License |
| pathable | 0.6.0 | Apache Software License |
| pathvalidate | 3.3.1 | MIT License |
| pillow | 12.3.0 | MIT-CMU |
| platformdirs | 4.11.5 | MIT |
| playwright | 1.62.0 | Apache-2.0 |
| pluggy | 1.6.0 | MIT License |
| pooch | 1.9.0 | BSD-3-Clause |
| pre_commit | 4.6.2 | MIT |
| propcache | 0.5.2 | Apache Software License |
| proto-plus | 1.28.4 | Apache Software License |
| protobuf | 7.36.0 | 3-Clause BSD License |
| psutil | 7.2.2 | BSD-3-Clause |
| py-key-value-aio | 0.4.5 | Apache-2.0 |
| py-vapid | 1.9.4 | MPL-2.0 |
| pyarrow | 25.0.1 | Apache-2.0 |
| pyasn1 | 0.6.4 | BSD-2-Clause |
| pyasn1_modules | 0.4.2 | BSD License |
| PyAutoGUI | 0.9.54 | BSD License |
| pybase64 | 1.5.0 | BSD-2-Clause |
| pycparser | 3.0 | BSD-3-Clause |
| pydantic | 2.13.5 | MIT |
| pydantic-settings | 2.15.0 | MIT |
| pydantic_core | 2.46.5 | MIT |
| pydub | 0.25.1 | MIT License |
| pyee | 13.0.1 | MIT License |
| pyflakes | 4.0.0 | MIT License |
| PyGetWindow | 0.0.9 | BSD License |
| Pygments | 2.21.0 | BSD-2-Clause |
| PyJWT | 2.13.0 | MIT |
| pyloudnorm | 0.2.0 | MIT |
| pyparsing | 3.3.2 | MIT |
| pypdf | 6.16.2 | BSD-3-Clause |
| pyperclip | 1.11.0 | BSD License |
| PyPika | 0.51.1 | Apache Software License |
| pyproject_hooks | 1.2.0 | MIT License |
| PyRect | 0.2.0 | BSD License |
| PyScreeze | 1.0.1 | MIT License |
| pytest | 9.1.1 | MIT |
| pytest-asyncio | 1.4.0 | Apache-2.0 |
| python-dateutil | 2.9.0.post0 | BSD License, Apache Software License |
| python-discovery | 1.6.0 | MIT License |
| python-dotenv | 1.2.3 | BSD-3-Clause |
| python-multipart | 0.0.32 | Apache-2.0 |
| pytweening | 1.2.0 | MIT License |
| pytz | 2026.3.post1 | MIT License |
| pywebpush | 2.5.0 | MPL-2.0 |
| pywin32 | 312 | Python Software Foundation License |
| pywin32-ctypes | 0.2.3 | BSD-3-Clause |
| pywinpty | 3.0.5 | MIT License |
| PyYAML | 6.0.3 | MIT License |
| qrcode | 8.2 | BSD License, Other/Proprietary License |
| RapidFuzz | 3.14.6 | MIT |
| referencing | 0.37.0 | MIT |
| regex | 2026.7.19 | Apache-2.0 AND CNRI-Python |
| requests | 2.34.2 | Apache Software License |
| requests-oauthlib | 2.0.0 | BSD License |
| resemble-perth | 1.0.1 | MIT License |
| rich | 15.0.0 | MIT License |
| rich-rst | 2.1.0 | MIT |
| rpds-py | 2026.6.3 | MIT |
| s3tokenizer | 0.3.0 | Apache2.0 |
| s3transfer | 0.16.1 | Apache Software License |
| safehttpx | 0.1.7 | MIT License |
| safetensors | 0.5.3 | Apache Software License |
| scikit-learn | 1.9.0 | BSD-3-Clause |
| scipy | 1.18.1 | BSD License |
| semantic-version | 2.10.0 | BSD License |
| shellingham | 1.5.4 | ISC License (ISCL) |
| six | 1.17.0 | MIT License |
| sniffio | 1.3.1 | MIT License, Apache Software License |
| soundfile | 0.14.0 | BSD License |
| soxr | 1.1.0 | LGPL-2.1-or-later |
| spacy_pkuseg | 1.0.1 | MIT License |
| srsly | 2.5.3 | MIT License |
| srt | 3.5.3 | MIT License |
| sse-starlette | 3.4.8 | BSD-3-Clause |
| standard-aifc | 3.13.0 | Python Software Foundation License |
| standard-chunk | 3.13.0 | Python Software Foundation License |
| standard-sunau | 3.13.0 | Python Software Foundation License |
| starlette | 1.6.0 | BSD-3-Clause |
| sympy | 1.13.1 | BSD License |
| tabulate | 0.10.0 | MIT |
| tenacity | 9.1.4 | Apache Software License |
| threadpoolctl | 3.6.0 | BSD License |
| tiktoken | 0.14.0 | MIT License |
| tokenizers | 0.22.2 | Apache Software License |
| tomlkit | 0.13.3 | MIT License |
| torch | 2.6.0 | BSD License |
| torchaudio | 2.6.0 | BSD License |
| tqdm | 4.70.0 | MPL-2.0 AND MIT |
| transformers | 5.2.0 | Apache 2.0 License |
| tree-sitter | 0.25.2 | MIT License |
| tree-sitter-bash | 0.25.1 | MIT License |
| tree-sitter-c | 0.24.2 | MIT License |
| tree-sitter-c-sharp | 0.23.5 | MIT License |
| tree-sitter-cpp | 0.23.4 | MIT License |
| tree-sitter-elixir | 0.3.5 | MIT License |
| tree-sitter-fortran | 0.6.0 | MIT License |
| tree-sitter-go | 0.25.0 | MIT |
| tree-sitter-groovy | 0.1.2 | MIT |
| tree-sitter-java | 0.23.5 | MIT License |
| tree-sitter-javascript | 0.25.0 | MIT |
| tree-sitter-json | 0.24.8 | MIT License |
| tree-sitter-julia | 0.23.1 | MIT License |
| tree-sitter-kotlin | 1.1.0 | MIT License |
| tree-sitter-lua | 0.5.0 | MIT |
| tree-sitter-objc | 3.0.2 | MIT |
| tree-sitter-php | 0.24.1 | MIT |
| tree-sitter-powershell | 0.26.4 | MIT |
| tree-sitter-python | 0.25.0 | MIT |
| tree-sitter-ruby | 0.23.1 | MIT License |
| tree-sitter-rust | 0.24.2 | MIT License |
| tree-sitter-scala | 0.26.2 | MIT License |
| tree-sitter-swift | 0.7.3 | MIT License |
| tree-sitter-typescript | 0.23.2 | MIT License |
| tree-sitter-verilog | 1.0.3 | MIT License |
| tree-sitter-zig | 1.1.2 | MIT |
| truststore | 0.10.4 | MIT |
| typer | 0.27.2 | MIT |
| typer-slim | 0.24.0 | MIT |
| typing-inspection | 0.4.4 | MIT |
| typing_extensions | 4.16.0 | PSF-2.0 |
| tzdata | 2026.3 | Apache-2.0 |
| uncalled-for | 0.4.0 | MIT License |
| uritemplate | 4.2.0 | BSD 3-Clause OR Apache-2.0 |
| urllib3 | 2.7.0 | MIT |
| uvicorn | 0.52.4 | BSD-3-Clause |
| virtualenv | 21.7.7 | MIT |
| vosk | 0.3.45 | Apache Software License |
| watchfiles | 1.2.0 | MIT License |
| websocket-client | 1.9.1 | Apache-2.0 |
| websockets | 17.1 | BSD-3-Clause |
| workspace-mcp | 1.25.2 | MIT |
| wrapt | 2.4.0 | BSD-2-Clause |
| x-wr-timezone | 2.0.1 | GNU Lesser General Public License v3 or later (LGPLv3+) |
| yarl | 1.24.5 | Apache-2.0 |
| yt-dlp | 2026.8.19 | Unlicense |
| zipp | 4.1.0 | MIT |

## JavaScript packages (51)

| Package | Version | License |
|---|---|---|
| @babel/runtime | 7.29.7 | MIT |
| @codemirror/autocomplete | 6.20.3 | MIT |
| @codemirror/commands | 6.11.0 | MIT |
| @codemirror/lang-cpp | 6.0.3 | MIT |
| @codemirror/lang-css | 6.3.1 | MIT |
| @codemirror/lang-html | 6.4.12 | MIT |
| @codemirror/lang-javascript | 6.2.5 | MIT |
| @codemirror/lang-json | 6.0.2 | MIT |
| @codemirror/lang-markdown | 6.5.2 | MIT |
| @codemirror/lang-python | 6.2.1 | MIT |
| @codemirror/lang-rust | 6.0.2 | MIT |
| @codemirror/language | 6.12.4 | MIT |
| @codemirror/lint | 6.9.7 | MIT |
| @codemirror/search | 6.7.2 | MIT |
| @codemirror/state | 6.7.4 | MIT |
| @codemirror/theme-one-dark | 6.1.3 | MIT |
| @codemirror/view | 6.43.11 | MIT |
| @fontsource-variable/geist | 5.3.0 | OFL-1.1 |
| @fontsource-variable/geist-mono | 5.3.0 | OFL-1.1 |
| @fontsource-variable/newsreader | 5.3.0 | OFL-1.1 |
| @lezer/common | 1.5.2 | MIT |
| @lezer/cpp | 1.1.6 | MIT |
| @lezer/css | 1.3.6 | MIT |
| @lezer/highlight | 1.2.3 | MIT |
| @lezer/html | 1.3.13 | MIT |
| @lezer/javascript | 1.5.4 | MIT |
| @lezer/json | 1.0.3 | MIT |
| @lezer/lr | 1.4.10 | MIT |
| @lezer/markdown | 1.7.2 | MIT |
| @lezer/python | 1.1.19 | MIT |
| @lezer/rust | 1.0.2 | MIT |
| @marijn/find-cluster-break | 1.0.4 | MIT |
| @uiw/codemirror-extensions-basic-setup | 4.25.11 | MIT |
| @uiw/react-codemirror | 4.25.11 | MIT |
| @xterm/addon-fit | 0.11.0 | MIT |
| @xterm/xterm | 6.0.0 | MIT |
| codemirror | 6.0.2 | MIT |
| commander | 15.0.0 | MIT |
| crelt | 1.0.7 | MIT |
| d3-dispatch | 3.0.1 | ISC |
| d3-force | 3.0.0 | ISC |
| d3-quadtree | 3.0.1 | ISC |
| d3-timer | 3.0.1 | ISC |
| js-tokens | 4.0.0 | MIT |
| katex | 0.18.9 | MIT |
| loose-envify | 1.4.0 | MIT |
| react | 18.3.1 | MIT |
| react-dom | 18.3.1 | MIT |
| scheduler | 0.23.2 | MIT |
| style-mod | 4.1.3 | MIT |
| w3c-keyname | 2.2.8 | MIT |
