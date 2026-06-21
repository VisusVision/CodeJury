"""Alakasiz teslim: HTML/CSS portfolio (Stack odevi degil)."""

PORTFOLIO_HTML = """<!doctype html>
<html lang="tr">
<head>
  <meta charset="utf-8" />
  <style>
    @media (max-width: 600px) {
      .grid { display: grid; grid-template-columns: 1fr; }
    }
    header { padding: 1rem; }
    section { margin: 1rem 0; }
  </style>
</head>
<body>
  <header><h1>Portfolyo</h1></header>
  <section class="grid"><article>Proje 1</article></section>
</body>
</html>
"""


def main() -> None:
    print(PORTFOLIO_HTML[:120])


if __name__ == "__main__":
    main()
