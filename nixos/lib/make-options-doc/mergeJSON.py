import collections
import json
import os
import sys
from typing import Any, Dict, List

# for MD conversion
import mistune
import re
from xml.sax.saxutils import escape, quoteattr

JSON = Dict[str, Any]

class Key:
    def __init__(self, path: List[str]):
        self.path = path
    def __hash__(self):
        result = 0
        for id in self.path:
            result ^= hash(id)
        return result
    def __eq__(self, other):
        return type(self) is type(other) and self.path == other.path

Option = collections.namedtuple('Option', ['name', 'value'])

# pivot a dict of options keyed by their display name to a dict keyed by their path
def pivot(options: Dict[str, JSON]) -> Dict[Key, Option]:
    result: Dict[Key, Option] = dict()
    for (name, opt) in options.items():
        result[Key(opt['loc'])] = Option(name, opt)
    return result

# pivot back to indexed-by-full-name
# like the docbook build we'll just fail if multiple options with differing locs
# render to the same option name.
def unpivot(options: Dict[Key, Option]) -> Dict[str, JSON]:
    result: Dict[str, Dict] = dict()
    for (key, opt) in options.items():
        if opt.name in result:
            raise RuntimeError(
                'multiple options with colliding ids found',
                opt.name,
                result[opt.name]['loc'],
                opt.value['loc'],
            )
        result[opt.name] = opt.value
    return result

manpage_urls = json.load(open(os.getenv('MANPAGE_URLS')))

admonitions = {
    '.warning': 'warning',
    '.important': 'important',
    '.note': 'note'
}
class Renderer(mistune.renderers.BaseRenderer):
    def _get_method(self, name):
        try:
            return super(Renderer, self)._get_method(name)
        except AttributeError:
            def not_supported(*args, **kwargs):
                raise NotImplementedError("md node not supported yet", name, args, **kwargs)
            return not_supported

    def text(self, text):
        return escape(text)
    def paragraph(self, text):
        return f"<para>{text}</para>"
    def newline(self):
        return "<para><literallayout>\n</literallayout></para>"
    def codespan(self, text):
        return f"<literal>{escape(text)}</literal>"
    def block_code(self, text, info=None):
        info = f" language={quoteattr(info)}" if info is not None else ""
        return f"<programlisting{info}>{escape(text)}</programlisting>"
    def link(self, link, text=None, title=None):
        tag = "link"
        if link[0:1] == '#':
            if text == "":
                tag = "xref"
            attr = "linkend"
            link = link[1:]
        else:
            # try to faithfully reproduce links that were of the form <link href="..."/>
            # in docbook format
            if text == link:
                text = ""
            attr = "xlink:href"
        return f"<{tag} {attr}=\"{link}\">{text}</{tag}>"
    def list(self, text, ordered, level, start=None):
        if ordered:
            raise NotImplementedError("ordered lists not supported yet")
        return f"<para><itemizedlist>\n{text}\n</itemizedlist></para>"
    def list_item(self, text, level):
        return f"<listitem>{text}</listitem>\n"
    def block_text(self, text):
        return self.paragraph(text)
    def emphasis(self, text):
        return f"<emphasis>{text}</emphasis>"
    def strong(self, text):
        return f"<emphasis role=\"strong\">{text}</emphasis>"
    def admonition(self, text, kind):
        if kind not in admonitions:
            raise NotImplementedError(f"admonition {kind} not supported yet")
        tag = admonitions[kind]
        return f"<para><{tag}>{text.rstrip()}</{tag}></para>"
    def block_quote(self, text):
        return f"<blockquote><para>{text}</para></blockquote>"
    def command(self, text):
        return f"<command>{escape(text)}</command>"
    def option(self, text):
        return f"<option>{escape(text)}</option>"
    def file(self, text):
        return f"<filename>{escape(text)}</filename>"
    def var(self, text):
        return f"<varname>{escape(text)}</varname>"
    def env(self, text):
        return f"<envar>{escape(text)}</envar>"
    def manpage(self, page, section):
        man = f"{page}({section})"
        title = f"<refentrytitle>{escape(page)}</refentrytitle>"
        vol = f"<manvolnum>{escape(section)}</manvolnum>"
        ref = f"<citerefentry>{title}{vol}</citerefentry>"
        if man in manpage_urls:
            return self.link(manpage_urls[man], text=ref)
        else:
            return ref

    def finalize(self, data):
        return "".join(data)

def p_command(md):
    COMMAND_PATTERN = r'\{command\}`(.*?)`'
    def parse(self, m, state):
        return ('command', m.group(1))
    md.inline.register_rule('command', COMMAND_PATTERN, parse)
    md.inline.rules.append('command')

def p_file(md):
    FILE_PATTERN = r'\{file\}`(.*?)`'
    def parse(self, m, state):
        return ('file', m.group(1))
    md.inline.register_rule('file', FILE_PATTERN, parse)
    md.inline.rules.append('file')

def p_var(md):
    VAR_PATTERN = r'\{var\}`(.*?)`'
    def parse(self, m, state):
        return ('var', m.group(1))
    md.inline.register_rule('var', VAR_PATTERN, parse)
    md.inline.rules.append('var')

def p_env(md):
    ENV_PATTERN = r'\{env\}`(.*?)`'
    def parse(self, m, state):
        return ('env', m.group(1))
    md.inline.register_rule('env', ENV_PATTERN, parse)
    md.inline.rules.append('env')

def p_option(md):
    OPTION_PATTERN = r'\{option\}`(.*?)`'
    def parse(self, m, state):
        return ('option', m.group(1))
    md.inline.register_rule('option', OPTION_PATTERN, parse)
    md.inline.rules.append('option')

def p_manpage(md):
    MANPAGE_PATTERN = r'\{manpage\}`(.*?)\((.+?)\)`'
    def parse(self, m, state):
        return ('manpage', m.group(1), m.group(2))
    md.inline.register_rule('manpage', MANPAGE_PATTERN, parse)
    md.inline.rules.append('manpage')

def p_admonition(md):
    ADMONITION_PATTERN = re.compile(r'^::: \{([^\n]*?)\}\n(.*?)^:::$\n*', flags=re.MULTILINE|re.DOTALL)
    def parse(self, m, state):
        return {
            'type': 'admonition',
            'children': self.parse(m.group(2), state),
            'params': [ m.group(1) ],
        }
    md.block.register_rule('admonition', ADMONITION_PATTERN, parse)
    md.block.rules.append('admonition')

md = mistune.create_markdown(renderer=Renderer(), plugins=[
    p_command, p_file, p_var, p_env, p_option, p_manpage, p_admonition
])

# converts in-place!
def convertMD(options: Dict[str, Any]) -> str:
    def convertString(path: str, text: str) -> str:
        try:
            rendered = md(text)
            return rendered
        except:
            print(f"error in {path}")
            raise

    def optionIs(option: Dict[str, Any], key: str, typ: str) -> bool:
        if key not in option: return False
        if type(option[key]) != dict: return False
        if '_type' not in option[key]: return False
        return option[key]['_type'] == typ

    def convertCode(name: str, option: Dict[str, Any], key: str):
        rendered = f"{key}-db"
        if optionIs(option, key, 'literalMD'):
            option[rendered] = convertString(name, f"*{key.capitalize()}:*\n{option[key]['text']}")
        elif optionIs(option, key, 'literalExpression'):
            code = option[key]['text']
            # for multi-line code blocks we only have to count ` runs at the beginning
            # of a line, but this is much easier.
            multiline = '\n' in code
            longest, current = (0, 0)
            for c in code:
                current = current + 1 if c == '`' else 0
                longest = max(current, longest)
            # inline literals need a space to separate ticks from content, code blocks
            # need newlines. inline literals need one extra tick, code blocks need three.
            ticks, sep = ('`' * (longest + (3 if multiline else 1)), '\n' if multiline else ' ')
            code = f"{ticks}{sep}{code}{sep}{ticks}"
            option[rendered] = convertString(name, f"*{key.capitalize()}:*\n{code}")
        elif optionIs(option, key, 'literalDocBook'):
            option[rendered] = f"<para><emphasis>{key.capitalize()}:</emphasis> {option[key]['text']}</para>"
        elif key in option:
            raise Exception(f"{name} {key} has unrecognized type", option[key])

    for (name, option) in options.items():
        try:
            if optionIs(option, 'description', 'mdDoc'):
                option['description'] = convertString(name, option['description']['text'])
            elif markdownByDefault:
                option['description'] = convertString(name, option['description'])
            else:
                option['description'] = ("<nixos:option-description><para>" +
                                         option['description'] +
                                         "</para></nixos:option-description>")

            convertCode(name, option, 'example')
            convertCode(name, option, 'default')

            if 'relatedPackages' in option:
                option['relatedPackages'] = convertString(name, option['relatedPackages'])
        except Exception as e:
            raise Exception(f"Failed to render option {name}: {str(e)}")


    return options

warningsAreErrors = False
warnOnDocbook = False
errorOnDocbook = False
markdownByDefault = False
optOffset = 0
for arg in sys.argv[1:]:
    if arg == "--warnings-are-errors":
        optOffset += 1
        warningsAreErrors = True
    if arg == "--warn-on-docbook":
        optOffset += 1
        warnOnDocbook = True
    elif arg == "--error-on-docbook":
        optOffset += 1
        errorOnDocbook = True
    if arg == "--markdown-by-default":
        optOffset += 1
        markdownByDefault = True

options = pivot(json.load(open(sys.argv[1 + optOffset], 'r')))
overrides = pivot(json.load(open(sys.argv[2 + optOffset], 'r')))

# fix up declaration paths in lazy options, since we don't eval them from a full nixpkgs dir
for (k, v) in options.items():
    # The _module options are not declared in nixos/modules
    if v.value['loc'][0] != "_module":
        v.value['declarations'] = list(map(lambda s: f'nixos/modules/{s}' if isinstance(s, str) else s, v.value['declarations']))

# merge both descriptions
for (k, v) in overrides.items():
    cur = options.setdefault(k, v).value
    for (ok, ov) in v.value.items():
        if ok == 'declarations':
            decls = cur[ok]
            for d in ov:
                if d not in decls:
                    decls += [d]
        elif ok == "type":
            # ignore types of placeholder options
            if ov != "_unspecified" or cur[ok] == "_unspecified":
                cur[ok] = ov
        elif ov is not None or cur.get(ok, None) is None:
            cur[ok] = ov

severity = "error" if warningsAreErrors else "warning"

def is_docbook(o, key):
    val = o.get(key, {})
    if not isinstance(val, dict):
        return False
    return val.get('_type', '') == 'literalDocBook'

# check that every option has a description
hasWarnings = False
hasErrors = False
hasDocBook = False
for (k, v) in options.items():
    if warnOnDocbook or errorOnDocbook:
        kind = "error" if errorOnDocbook else "warning"
        if isinstance(v.value.get('description', {}), str):
            hasErrors |= errorOnDocbook
            hasDocBook = True
            print(
                f"\x1b[1;31m{kind}: option {v.name} description uses DocBook\x1b[0m",
                file=sys.stderr)
        elif is_docbook(v.value, 'defaultText'):
            hasErrors |= errorOnDocbook
            hasDocBook = True
            print(
                f"\x1b[1;31m{kind}: option {v.name} default uses DocBook\x1b[0m",
                file=sys.stderr)
        elif is_docbook(v.value, 'example'):
            hasErrors |= errorOnDocbook
            hasDocBook = True
            print(
                f"\x1b[1;31m{kind}: option {v.name} example uses DocBook\x1b[0m",
                file=sys.stderr)

    if v.value.get('description', None) is None:
        hasWarnings = True
        print(f"\x1b[1;31m{severity}: option {v.name} has no description\x1b[0m", file=sys.stderr)
        v.value['description'] = "This option has no description."
    if v.value.get('type', "unspecified") == "unspecified":
        hasWarnings = True
        print(
            f"\x1b[1;31m{severity}: option {v.name} has no type. Please specify a valid type, see " +
            "https://nixos.org/manual/nixos/stable/index.html#sec-option-types\x1b[0m", file=sys.stderr)

if hasDocBook:
    (why, what) = (
        ("disallowed for in-tree modules", "contribution") if errorOnDocbook
        else ("deprecated for option documentation", "module")
    )
    print("Explanation: The documentation contains descriptions, examples, or defaults written in DocBook. " +
        "NixOS is in the process of migrating from DocBook to Markdown, and " +
        f"DocBook is {why}. To change your {what} to "+
        "use Markdown, apply mdDoc and literalMD and use the *MD variants of option creation " +
        "functions where they are available. For example:\n" +
        "\n" +
        "  example.foo = mkOption {\n" +
        "    description = lib.mdDoc ''your description'';\n" +
        "    defaultText = lib.literalMD ''your description of default'';\n" +
        "  };\n" +
        "\n" +
        "  example.enable = mkEnableOption (lib.mdDoc ''your thing'');\n" +
        "  example.package = mkPackageOptionMD pkgs \"your-package\" {};\n" +
        "  imports = [ (mkAliasOptionModuleMD [ \"example\" \"args\" ] [ \"example\" \"settings\" ]) ];",
        file = sys.stderr)
    with open(os.getenv('TOUCH_IF_DB'), 'x'):
        # just make sure it exists
        pass

if hasErrors:
    sys.exit(1)
if hasWarnings and warningsAreErrors:
    print(
        "\x1b[1;31m" +
        "Treating warnings as errors. Set documentation.nixos.options.warningsAreErrors " +
        "to false to ignore these warnings." +
        "\x1b[0m",
        file=sys.stderr)
    sys.exit(1)

json.dump(convertMD(unpivot(options)), fp=sys.stdout)
