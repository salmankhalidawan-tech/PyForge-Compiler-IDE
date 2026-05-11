"""
PyForge Backend — Compiler Construction Edition
================================================
Full compiler pipeline:
  1. Lexical Analysis  (tokenizer via tokenize module)
  2. Syntax Analysis   (AST generation via ast module)
  3. Semantic Analysis (scope, type hints, undefined names)
  4. IR / Bytecode     (dis module — CPython bytecode)
  5. Execution         (exec with sandboxed globals)
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
import sys, io, traceback, ast, threading, time
import os, base64, tokenize, dis, token as token_mod
import types
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

app = Flask(__name__)
CORS(app)

TIMEOUT_SECONDS = 30

AVAILABLE_LIBRARIES = [
    "math", "random", "datetime", "os", "sys", "re", "json", "csv",
    "collections", "itertools", "functools", "string", "time", "copy",
    "pathlib", "glob", "shutil", "subprocess", "threading", "multiprocessing",
    "hashlib", "hmac", "secrets", "base64", "struct", "io", "tempfile",
    "contextlib", "abc", "typing", "dataclasses", "enum", "pprint",
    "textwrap", "decimal", "fractions", "statistics", "heapq", "bisect",
    "array", "queue", "unittest", "logging", "argparse", "configparser",
    "pickle", "shelve", "sqlite3", "urllib", "http", "email", "html",
    "xml", "zipfile", "tarfile", "gzip", "bz2", "lzma",
    "numpy", "pandas", "matplotlib", "scipy", "sympy", "PIL", "requests"
]


# ─────────────────────────────────────────────────────────────
# STAGE 1 — LEXICAL ANALYSIS
# ─────────────────────────────────────────────────────────────
def lexical_analysis(code: str) -> dict:
    """Tokenise the source using Python's tokenize module."""
    tokens = []
    errors = []

    TOKEN_CATEGORIES = {
        token_mod.NAME:      "IDENTIFIER",
        token_mod.NUMBER:    "NUMBER_LITERAL",
        token_mod.STRING:    "STRING_LITERAL",
        token_mod.OP:        "OPERATOR",
        token_mod.COMMENT:   "COMMENT",
        token_mod.NEWLINE:   "NEWLINE",
        token_mod.NL:        "NL",
        token_mod.INDENT:    "INDENT",
        token_mod.DEDENT:    "DEDENT",
        token_mod.ENCODING:  "ENCODING",
        token_mod.ENDMARKER: "EOF",
        token_mod.ERRORTOKEN:"ERROR",
    }

    import keyword as kw_mod
    try:
        reader = io.StringIO(code).readline
        for tok in tokenize.generate_tokens(reader):
            tok_type = tok.type
            tok_name = token_mod.tok_name.get(tok_type, str(tok_type))
            category = TOKEN_CATEGORIES.get(tok_type, tok_name)

            if tok_type == token_mod.NAME and kw_mod.iskeyword(tok.string):
                category = "KEYWORD"
            elif tok_type == token_mod.NAME and tok.string in dir(__builtins__):
                category = "BUILTIN"

            if tok_type not in (token_mod.NEWLINE, token_mod.NL,
                                 token_mod.INDENT, token_mod.DEDENT,
                                 token_mod.ENCODING, token_mod.ENDMARKER,
                                 token_mod.COMMENT):
                tokens.append({
                    "line":     tok.start[0],
                    "col":      tok.start[1],
                    "type":     tok_name,
                    "category": category,
                    "value":    tok.string,
                })
    except tokenize.TokenError as e:
        errors.append(str(e))

    from collections import Counter
    cat_counts = Counter(t["category"] for t in tokens)

    return {
        "tokens": tokens,
        "token_count": len(tokens),
        "category_summary": dict(cat_counts),
        "errors": errors,
        "success": len(errors) == 0,
    }


# ─────────────────────────────────────────────────────────────
# STAGE 2 — SYNTAX ANALYSIS (Parse to AST)
# ─────────────────────────────────────────────────────────────
def syntax_analysis(code: str) -> dict:
    """Parse the code into an AST and return a human-readable tree."""
    try:
        tree = ast.parse(code, filename="<source>")
    except SyntaxError as e:
        return {
            "success": False,
            "error": {
                "type":    "SyntaxError",
                "message": e.msg,
                "line":    e.lineno,
                "col":     e.offset,
                "text":    e.text,
            },
            "ast_tree": None,
            "node_count": 0,
            "definitions": [],
        }

    def node_repr(node, depth=0):
        if depth > 12:
            return None
        name = type(node).__name__
        fields = {}
        for field_name, value in ast.iter_fields(node):
            if field_name in ("body", "orelse", "handlers", "finalbody", "type_ignores"):
                continue
            if isinstance(value, ast.AST):
                fields[field_name] = node_repr(value, depth + 1)
            elif isinstance(value, list):
                items = [node_repr(v, depth + 1) if isinstance(v, ast.AST)
                         else str(v) for v in value[:6]]
                if items:
                    fields[field_name] = items
            elif value is not None:
                fields[field_name] = str(value)

        children = []
        for child in ast.iter_child_nodes(node):
            r = node_repr(child, depth + 1)
            if r:
                children.append(r)

        result = {"node": name}
        if fields:
            result["fields"] = fields
        if children:
            result["children"] = children
        if hasattr(node, "lineno"):
            result["line"] = node.lineno
        return result

    tree_repr = node_repr(tree)
    node_count = sum(1 for _ in ast.walk(tree))

    definitions = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = [a.arg for a in node.args.args]
            definitions.append({
                "kind": "function",
                "name": node.name,
                "args": args,
                "line": node.lineno,
                "decorators": [ast.unparse(d) for d in node.decorator_list],
            })
        elif isinstance(node, ast.ClassDef):
            bases = [ast.unparse(b) for b in node.bases]
            definitions.append({
                "kind": "class",
                "name": node.name,
                "bases": bases,
                "line": node.lineno,
            })
        elif isinstance(node, ast.Import):
            for alias in node.names:
                definitions.append({
                    "kind": "import",
                    "name": alias.name,
                    "alias": alias.asname,
                    "line": node.lineno,
                })
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                definitions.append({
                    "kind": "import",
                    "name": f"{node.module}.{alias.name}",
                    "alias": alias.asname,
                    "line": node.lineno,
                })

    return {
        "success": True,
        "error": None,
        "ast_tree": tree_repr,
        "node_count": node_count,
        "definitions": definitions,
    }


# ─────────────────────────────────────────────────────────────
# STAGE 3 — SEMANTIC ANALYSIS
# ─────────────────────────────────────────────────────────────
def semantic_analysis(code: str) -> dict:
    warnings = []
    errors   = []

    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return {"success": False, "errors": [{"type": "SyntaxError",
                "message": f"{e.msg}", "line": e.lineno}],
                "warnings": [], "scope_info": {}}

    assigned = set()
    imported = {}

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    assigned.add(t.id)
        elif isinstance(node, ast.AugAssign):
            if isinstance(node.target, ast.Name):
                assigned.add(node.target.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            assigned.add(node.name)
            for arg in node.args.args:
                assigned.add(arg.arg)
        elif isinstance(node, ast.ClassDef):
            assigned.add(node.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                n = alias.asname or alias.name.split(".")[0]
                imported[n] = node.lineno
                assigned.add(n)
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                n = alias.asname or alias.name
                if n != "*":
                    imported[n] = node.lineno
                    assigned.add(n)
        elif isinstance(node, ast.For):
            if isinstance(node.target, ast.Name):
                assigned.add(node.target.id)
        elif isinstance(node, ast.NamedExpr):
            if isinstance(node.target, ast.Name):
                assigned.add(node.target.id)
        elif isinstance(node, ast.withitem):
            if node.optional_vars and isinstance(node.optional_vars, ast.Name):
                assigned.add(node.optional_vars.id)
        elif isinstance(node, ast.ExceptHandler):
            if node.name:
                assigned.add(node.name)

    # Add comprehension targets
    for node in ast.walk(tree):
        if isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            for gen in (node.generators if hasattr(node, 'generators') else []):
                if isinstance(gen.target, ast.Name):
                    assigned.add(gen.target.id)

    import builtins
    builtin_names = set(dir(builtins))

    used = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            used.add((node.id, getattr(node, "lineno", "?")))

    for name, line in used:
        if (name not in assigned
                and name not in builtin_names
                and name not in ("__name__", "__file__", "__doc__",
                                  "True", "False", "None", "self", "cls")):
            errors.append({
                "type": "UndefinedName",
                "message": f"Name '{name}' may not be defined before use",
                "line": line,
            })

    used_names = {n for n, _ in used}
    for name, line in imported.items():
        if name not in used_names and name != "_":
            warnings.append({
                "type": "UnusedImport",
                "message": f"'{name}' is imported but never used",
                "line": line,
            })

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id in builtin_names:
                    warnings.append({
                        "type": "ShadowedBuiltin",
                        "message": f"Assignment to '{t.id}' shadows a Python builtin",
                        "line": getattr(node, "lineno", "?"),
                    })

    TERMINATORS = (ast.Return, ast.Raise, ast.Break, ast.Continue)
    for node in ast.walk(tree):
        if hasattr(node, "body") and isinstance(node.body, list):
            for i, stmt in enumerate(node.body[:-1]):
                if isinstance(stmt, TERMINATORS):
                    warnings.append({
                        "type": "UnreachableCode",
                        "message": "Statements after this are unreachable",
                        "line": getattr(stmt, "lineno", "?"),
                    })
                    break

    scope_info = {
        "module_level_names": sorted(assigned),
        "imported_names": sorted(imported.keys()),
        "used_names": sorted(used_names),
    }

    return {
        "success": len(errors) == 0,
        "errors":   errors,
        "warnings": warnings,
        "scope_info": scope_info,
    }


# ─────────────────────────────────────────────────────────────
# STAGE 4 — BYTECODE / IR
# ─────────────────────────────────────────────────────────────
def bytecode_analysis(code: str) -> dict:
    """Compile to CPython bytecode and disassemble."""
    try:
        compiled = compile(code, "<source>", "exec")
    except SyntaxError as e:
        return {"success": False, "error": str(e), "instructions": [],
                "const_count": 0, "name_count": 0, "code_objects": []}

    buf = io.StringIO()
    old = sys.stdout
    sys.stdout = buf
    dis.dis(compiled)
    sys.stdout = old
    raw = buf.getvalue()

    instructions = [line.rstrip() for line in raw.splitlines() if line.strip()]

    def collect_code_objects(co, depth=0):
        result = []
        result.append({
            "name":       co.co_name,
            "depth":      depth,
            "firstline":  co.co_firstlineno,
            "argcount":   co.co_argcount,
            "locals":     list(co.co_varnames),
            "constants":  [repr(c) for c in co.co_consts
                           if not isinstance(c, types.CodeType)],
            "names":      list(co.co_names),
        })
        for const in co.co_consts:
            if isinstance(const, types.CodeType):
                result.extend(collect_code_objects(const, depth + 1))
        return result

    code_objects = collect_code_objects(compiled)

    return {
        "success": True,
        "error": None,
        "instructions": instructions,
        "const_count": len(compiled.co_consts),
        "name_count": len(compiled.co_names),
        "code_objects": code_objects,
    }


# ─────────────────────────────────────────────────────────────
# STAGE 5 — EXECUTION
# ─────────────────────────────────────────────────────────────
def run_code_with_timeout(code, timeout=TIMEOUT_SECONDS):
    result = {"output": "", "error": "", "plot": None}

    old_stdout, old_stderr = sys.stdout, sys.stderr
    sys.stdout = io.StringIO()
    sys.stderr = io.StringIO()
    plt.close('all')

    exec_globals = {"__builtins__": __builtins__, "__name__": "__main__"}

    try:
        import numpy as np, pandas as pd
        import matplotlib.pyplot as plt_module
        import math, random, datetime, re, json, csv
        import os, sys as sys_mod, time, copy, collections, itertools, functools
        from pathlib import Path
        import statistics, decimal, fractions, heapq, bisect, queue
        from typing import List, Dict, Tuple, Optional, Any, Union
        from dataclasses import dataclass, field
        from enum import Enum, auto
        from functools import reduce, partial
        from collections import Counter, defaultdict, OrderedDict, deque, namedtuple
        import string, textwrap, pprint, hashlib, base64 as b64, struct
        import io as io_mod, contextlib, abc
        from itertools import product, permutations, combinations, chain
        import sympy
        from PIL import Image

        exec_globals.update({
            "np": np, "numpy": np, "pd": pd, "pandas": pd,
            "plt": plt_module, "matplotlib": matplotlib,
            "math": math, "random": random, "datetime": datetime,
            "re": re, "json": json, "csv": csv, "os": os, "time": time,
            "copy": copy, "collections": collections,
            "itertools": itertools, "functools": functools,
            "Path": Path, "statistics": statistics,
            "decimal": decimal, "fractions": fractions,
            "heapq": heapq, "bisect": bisect, "queue": queue,
            "List": List, "Dict": Dict, "Tuple": Tuple,
            "Optional": Optional, "Any": Any, "Union": Union,
            "dataclass": dataclass, "field": field,
            "Enum": Enum, "auto": auto, "reduce": reduce, "partial": partial,
            "Counter": Counter, "defaultdict": defaultdict,
            "OrderedDict": OrderedDict, "deque": deque, "namedtuple": namedtuple,
            "string": string, "textwrap": textwrap, "pprint": pprint,
            "hashlib": hashlib, "b64": b64, "struct": struct,
            "io": io_mod, "contextlib": contextlib, "abc": abc,
            "product": product, "permutations": permutations,
            "combinations": combinations, "chain": chain,
            "sympy": sympy, "Image": Image,
        })
    except ImportError:
        pass

    execution_result = {"done": False, "error": None}

    def execute():
        try:
            exec(compile(code, "<string>", "exec"), exec_globals)
        except Exception as e:
            execution_result["error"] = traceback.format_exc()
        finally:
            execution_result["done"] = True

    thread = threading.Thread(target=execute, daemon=True)
    thread.start()
    thread.join(timeout=timeout)

    output       = sys.stdout.getvalue()
    error_output = sys.stderr.getvalue()
    sys.stdout   = old_stdout
    sys.stderr   = old_stderr

    if not execution_result["done"]:
        result["error"] = f"Execution timed out after {timeout} seconds."
        return result

    if execution_result["error"]:
        result["error"] = execution_result["error"]

    result["output"] = output
    if error_output:
        result["error"] = (result["error"] + "\n" + error_output).strip()

    figs = [plt.figure(i) for i in plt.get_fignums()]
    if figs:
        buf = io.BytesIO()
        figs[-1].savefig(buf, format='png', bbox_inches='tight', dpi=150)
        buf.seek(0)
        result["plot"] = base64.b64encode(buf.read()).decode('utf-8')
        plt.close('all')

    return result


def check_syntax(code):
    try:
        ast.parse(code)
        return None
    except SyntaxError as e:
        return f"SyntaxError on line {e.lineno}: {e.msg}\n  {e.text}"


# ─────────────────────────────────────────────────────────────
# API ROUTES
# ─────────────────────────────────────────────────────────────

@app.route('/run', methods=['POST'])
def run_code():
    """Backward-compatible run endpoint."""
    data = request.get_json()
    code = data.get('code', '').strip()
    if not code:
        return jsonify({"output": "", "error": "No code provided.", "plot": None})
    syntax_error = check_syntax(code)
    if syntax_error:
        return jsonify({"output": "", "error": syntax_error, "plot": None})
    result = run_code_with_timeout(code)
    return jsonify(result)


@app.route('/compile', methods=['POST'])
def compile_pipeline():
    """Full compiler pipeline: lex -> parse -> semantic -> bytecode -> execute."""
    data = request.get_json()
    code = data.get('code', '').strip()
    if not code:
        return jsonify({"error": "No code provided."})

    t0 = time.time()

    t1s = time.time(); lex = lexical_analysis(code);  t1e = time.time()
    t2s = time.time(); syn = syntax_analysis(code);   t2e = time.time()

    if syn["success"]:
        t3s = time.time(); sem = semantic_analysis(code); t3e = time.time()
        t4s = time.time(); bc  = bytecode_analysis(code); t4e = time.time()
        t5s = time.time(); ex  = run_code_with_timeout(code); t5e = time.time()
    else:
        t3s = t3e = t4s = t4e = t5s = t5e = time.time()
        sem = {"success": False, "errors": [{"type":"Skipped","message":"Parse failed","line":0}],
               "warnings": [], "scope_info": {}}
        bc  = {"success": False, "error": "Skipped", "instructions": [],
               "const_count": 0, "name_count": 0, "code_objects": []}
        ex  = {"output": "", "error": "Execution skipped — fix syntax errors first.", "plot": None}

    return jsonify({
        "timings": {
            "lexer":    round((t1e - t1s) * 1000, 3),
            "parser":   round((t2e - t2s) * 1000, 3),
            "semantic": round((t3e - t3s) * 1000, 3),
            "bytecode": round((t4e - t4s) * 1000, 3),
            "execute":  round((t5e - t5s) * 1000, 3),
            "total":    round((time.time() - t0) * 1000, 2),
        },
        "stages": {
            "lexer":    lex,
            "parser":   syn,
            "semantic": sem,
            "bytecode": bc,
            "execute":  ex,
        }
    })


@app.route('/analyze', methods=['POST'])
def analyze_only():
    """Analysis only (no execution)."""
    data = request.get_json()
    code = data.get('code', '').strip()
    if not code:
        return jsonify({"error": "No code provided."})
    lex = lexical_analysis(code)
    syn = syntax_analysis(code)
    sem = semantic_analysis(code) if syn["success"] else {"success": False, "errors":[], "warnings":[], "scope_info":{}}
    bc  = bytecode_analysis(code) if syn["success"] else {"success": False, "error":"skipped","instructions":[],"const_count":0,"name_count":0,"code_objects":[]}
    return jsonify({"lexer": lex, "parser": syn, "semantic": sem, "bytecode": bc})


@app.route('/libraries', methods=['GET'])
def get_libraries():
    available = []
    for lib in AVAILABLE_LIBRARIES:
        try:
            __import__(lib)
            available.append({"name": lib, "available": True})
        except ImportError:
            available.append({"name": lib, "available": False})
    return jsonify(available)


@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok", "python": sys.version})


if __name__ == '__main__':
    print("PyForge Compiler Backend running on http://localhost:5000")
    print("Endpoints: /run  /compile  /analyze  /libraries  /health")
    app.run(host='0.0.0.0', port=5000, debug=False)
