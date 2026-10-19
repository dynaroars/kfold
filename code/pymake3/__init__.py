# source: Mozilla pymake, a GNU-Make-compatible Make implementation in Python 2
#   https://github.com/mozilla/pymake (archived, no releases)
#   final revision 034ae9ea5b726e03647d049147c5dbf688e94aaf (2014-07-08), MIT license (LICENSE)
#
# adaptation: Python 3 port; package imports renamed from pymake to pymake3, the unused
# imp import removed for Python 3.12+, and the Windows-only import fixed to pymake3
#
# the tool uses only the parser: parser.parsestring, parser.parsemakesyntax, and the
# statement and expansion classes in parserdata, data and functions
#
# the pymake3 package on PyPI is an unrelated build tool with the same import name
