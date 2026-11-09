import ast, sys, pathlib
root = pathlib.Path(sys.argv[1])
AUTHN = ("get_current_user","require_admin","require_","get_tenant","current_user","require","platform_admin","verify","get_user")
for f in sorted(root.rglob("*.py")):
    if "/tests/" in str(f) or "validation_tests" in str(f): continue
    try: tree = ast.parse(f.read_text())
    except Exception: continue
    for n in ast.walk(tree):
        if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)):
            for d in n.decorator_list:
                if isinstance(d,ast.Call) and isinstance(d.func,ast.Attribute) and d.func.attr in ("get","post","put","patch","delete","api_route","websocket"):
                    path = d.args[0].value if d.args and isinstance(d.args[0],ast.Constant) else "?"
                    src = ast.unparse(n.args) + " " + " ".join(ast.unparse(x) for x in d.keywords)
                    if not any(a in src for a in AUTHN):
                        print(f"{f.relative_to(root)}:{n.lineno} {d.func.attr.upper()} {path}  args=({src[:140]})")
