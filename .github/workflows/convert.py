#!/usr/bin/env python3
"""Adapt the Vulkan registry (vk.xml) into an object-oriented JSON document.

Named collections become objects keyed by name, comma separated attributes
become arrays, C declarations are decomposed into type/pointer/array fields
and numeric attributes become numbers.  Standard library only.
"""

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET

# Attributes holding comma separated lists.
LIST_ATTRS = {
    "api", "supported", "ratified", "structextends", "successcodes",
    "errorcodes", "export", "queues", "tasks", "cmdbufferlevel", "renderpass",
    "videocoding", "len", "altlen", "optional", "validstructs", "allowduplicate",
    "depends_list", "comment_list", "externsync_list", "returnedonly_list",
    "requires_list", "promotedto_list",
}
# Attributes holding booleans.
BOOL_ATTRS = {
    "returnedonly", "noautovalidity", "nofeatures", "deprecated_bool",
    "limittype_bool", "alias_bool", "dispatchable",
}
# Attributes converted to int when they look like integers.
INT_ATTRS = {
    "value", "bitpos", "offset", "extnumber", "number", "bitwidth",
    "blockSize", "texelsPerBlock", "packed", "blockExtent_int", "bits",
    "id", "width", "height", "depth",
}
# Attribute renames to camelCase.
RENAME = {
    "successcodes": "successCodes", "errorcodes": "errorCodes",
    "structextends": "structExtends", "returnedonly": "returnedOnly",
    "noautovalidity": "noAutoValidity", "validstructs": "validStructs",
    "cmdbufferlevel": "cmdBufferLevel", "renderpass": "renderPass",
    "videocoding": "videoCoding", "extnumber": "extNumber",
    "externsync": "externSync", "altlen": "altLen", "objecttype": "objectType",
    "limittype": "limitType", "featurelink": "featureLink",
    "nofeatures": "noFeatures", "promotedto": "promotedTo",
    "deprecatedby": "deprecatedBy", "obsoletedby": "obsoletedBy",
    "allowduplicate": "allowDuplicate", "bitvalues": "bitValues",
    "parentstruct": "parentStruct",
}

INT_RE = re.compile(r"^-?(0[xX][0-9a-fA-F]+|[0-9]+)$")


def to_int(value):
    if INT_RE.match(value):
        return int(value, 16) if value.lower().lstrip("-").startswith("0x") else int(value, 10)
    return value


def convert_attrs(attrib, skip=()):
    """Convert an XML attribute dict to a JSON friendly dict."""
    out = {}
    for key, value in attrib.items():
        if key in skip:
            continue
        if key in LIST_ATTRS:
            items = [v.strip() for v in value.split(",") if v.strip()]
            if key == "optional":
                items = [i == "true" for i in items]
            out[RENAME.get(key, key)] = items
            continue
        if key in BOOL_ATTRS and value in ("true", "false"):
            value = value == "true"
        elif key in INT_ATTRS:
            value = to_int(value)
        out[RENAME.get(key, key)] = value
    return out


def add_named(target, name, obj):
    """Insert into dict; duplicates (e.g. vulkan vs vulkansc) become variants."""
    if name in target:
        target[name].setdefault("variants", []).append(obj)
    else:
        target[name] = obj


def clean(text):
    return " ".join((text or "").split())


def parse_decl(elem):
    """Decompose a <member>/<param>/<proto> C declaration."""
    out = {}
    name_el = elem.find("name")
    type_el = elem.find("type")
    out["name"] = name_el.text if name_el is not None else None
    if type_el is not None:
        out["type"] = type_el.text
        prefix = (elem.text or "").split()
        tail = type_el.tail or ""
        if "const" in prefix:
            out["const"] = True
        if "struct" in prefix:
            out["struct"] = True
        depth = tail.count("*")
        if depth:
            out["pointer"] = depth
            if "const" in tail:
                out["constPointer"] = True
    # arrays / bitfields follow the name
    if name_el is not None:
        after = name_el.tail or ""
        children = list(elem)
        for sib in children[children.index(name_el) + 1:]:
            if sib.tag == "enum":
                after += (sib.text or "") + (sib.tail or "")
        dims = re.findall(r"\[([^\]]*)\]", after)
        if dims:
            out["array"] = [to_int(d.strip()) for d in dims]
        bits = re.search(r":\s*(\d+)", after)
        if bits:
            out["bitfield"] = int(bits.group(1))
    comment = elem.find("comment")
    if comment is not None:
        out["comment"] = clean("".join(comment.itertext()))
    out.update(convert_attrs(elem.attrib))
    return out


def convert_platforms(root):
    return {p.get("name"): convert_attrs(p.attrib, skip=("name",)) for p in root}


def convert_tags(root):
    return {t.get("name"): convert_attrs(t.attrib, skip=("name",)) for t in root}


def convert_types(root):
    types = {}
    for t in root.iterfind("type"):
        category = t.get("category")
        name = t.get("name") or t.findtext("name")
        if not name:
            continue
        obj = {}
        if category:
            obj["category"] = category
        if t.get("alias"):
            obj.update(convert_attrs(t.attrib, skip=("name", "category")))
            add_named(types, name, obj)
            continue
        obj.update(convert_attrs(t.attrib, skip=("name", "category")))
        if category in ("struct", "union"):
            obj["members"] = [parse_decl(m) for m in t.iterfind("member")]
        elif category == "handle":
            type_el = t.find("type")
            obj["dispatchable"] = type_el is not None and type_el.text == "VK_DEFINE_HANDLE"
        elif category in ("basetype", "bitmask"):
            type_el = t.find("type")
            if type_el is not None:
                obj["baseType"] = type_el.text
        elif category == "funcpointer":
            proto = t.find("proto")
            if proto is not None:
                decl = parse_decl(proto)
                obj["returnType"] = decl.get("type")
                obj["params"] = [parse_decl(p) for p in t.iterfind("param")]
            else:
                obj["text"] = clean("".join(t.itertext()))
        elif category in ("define", "include"):
            obj["text"] = clean("".join(t.itertext()))
        add_named(types, name, obj)
    return types


def convert_enums(root):
    enums, constants = {}, {}
    for group in root.iterfind("enums"):
        name = group.get("name")
        values = {}
        unused = []
        for e in group:
            if e.tag == "enum":
                add_named(values, e.get("name"), convert_attrs(e.attrib, skip=("name",)))
            elif e.tag == "unused":
                unused.append(convert_attrs(e.attrib))
        if name == "API Constants":
            constants.update(values)
            continue
        obj = convert_attrs(group.attrib, skip=("name",))
        obj["values"] = values
        if unused:
            obj["unused"] = unused
        enums[name] = obj
    return enums, constants


def convert_commands(root):
    commands = {}
    for c in root.iterfind("command"):
        if c.get("alias"):
            add_named(commands, c.get("name"), convert_attrs(c.attrib, skip=("name",)))
            continue
        proto = parse_decl(c.find("proto"))
        obj = convert_attrs(c.attrib)
        obj["returnType"] = proto.get("type")
        obj["params"] = [parse_decl(p) for p in c.iterfind("param")]
        sync = [clean("".join(i.itertext())) for i in c.iterfind("implicitexternsyncparams/param")]
        if sync:
            obj["implicitExternSyncParams"] = sync
        add_named(commands, proto["name"], obj)
    return commands


def convert_block(block):
    """Convert a <require>/<remove>/<deprecate> block."""
    out = convert_attrs(block.attrib)
    for child in block:
        key = {"type": "types", "command": "commands", "enum": "enums",
               "feature": "features", "comment": "comments"}.get(child.tag, child.tag)
        if child.tag in ("type", "command"):
            out.setdefault(key, []).append(child.get("name"))
        elif child.tag == "comment":
            out.setdefault(key, []).append(clean(child.text))
        else:
            out.setdefault(key, []).append(convert_attrs(child.attrib))
    return out


def convert_feature_like(elem):
    obj = convert_attrs(elem.attrib, skip=("name",))
    for child in elem:
        if child.tag in ("require", "remove", "deprecate"):
            obj.setdefault(child.tag, []).append(convert_block(child))
    return obj


def convert_features(root):
    features = {}
    for f in root.iterfind("feature"):
        add_named(features, f.get("name"), convert_feature_like(f))
    return features


def convert_extensions(root):
    extensions = {}
    for e in root.iterfind("extension"):
        add_named(extensions, e.get("name"), convert_feature_like(e))
    return extensions


def generic_obj(elem):
    """Generic structural conversion: attributes + grouped children."""
    obj = convert_attrs(elem.attrib, skip=("name",))
    for child in elem:
        if child.tag == "comment":
            obj.setdefault("comments", []).append(clean("".join(child.itertext())))
            continue
        item = generic_obj(child)
        if child.get("name") is not None:
            item = {"name": child.get("name"), **item}
        obj.setdefault(child.tag + "s", []).append(item)
    text = clean(elem.text)
    if text and not len(elem):
        obj["text"] = text
    return obj


def generic_collection(container):
    """Name-keyed objects; grouped by tag when the container is heterogeneous."""
    tags = {c.tag for c in container if c.tag != "comment"}
    groups = {}
    for child in container:
        if child.tag == "comment":
            continue
        name = child.get("name")
        obj = generic_obj(child)
        if name is None:
            groups.setdefault(child.tag, []).append(obj)
        else:
            add_named(groups.setdefault(child.tag, {}), name, obj)
    if len(tags) == 1:
        return next(iter(groups.values()))
    return groups


def header_version(root):
    for t in root.iter("type"):
        if t.get("category") == "define" and t.findtext("name") == "VK_HEADER_VERSION":
            m = re.search(r"VK_HEADER_VERSION\s+(\d+)", "".join(t.itertext()))
            if m:
                return int(m.group(1))
    return None

def header_version_complete(root):
    for t in root.iter("type"):
        # Versioning is based on the main variant
        if t.get("category") == "define" and t.findtext("name") == "VK_HEADER_VERSION_COMPLETE" and "vulkan" in t.get("api").split(","):
            m = re.search(r"VK_MAKE_API_VERSION\(0, (\d+), (\d+), VK_HEADER_VERSION\)", "".join(t.itertext()))
            if m:
                return f"{int(m.group(1))}.{int(m.group(2))}.{int(header_version(root) or 0)}"
    return None


def convert(path, commit=None):
    root = ET.parse(path).getroot()
    result = {"meta": {
        "source": "KhronosGroup/Vulkan-Docs",
        "commit": commit,
        "headerVersion": header_version_complete(root),
    }}
    enums, constants = {}, {}
    sections = {}
    for child in root:
        if child.tag == "comment":
            if len(result["meta"].setdefault("license", [])) < 2:
                result["meta"]["license"].append((child.text or "").strip())
        elif child.tag == "platforms":
            sections["platforms"] = convert_platforms(child)
        elif child.tag == "tags":
            sections["tags"] = convert_tags(child)
        elif child.tag == "types":
            sections["types"] = convert_types(child)
        elif child.tag == "enums":
            e, c = convert_enums(ET.fromstring("<r>" + ET.tostring(child, encoding="unicode") + "</r>"))
            enums.update(e)
            constants.update(c)
        elif child.tag == "commands":
            sections["commands"] = convert_commands(child)
        elif child.tag == "feature":
            add_named(sections.setdefault("features", {}), child.get("name"), convert_feature_like(child))
        elif child.tag == "extensions":
            sections["extensions"] = convert_extensions(child)
        elif child.tag in ("formats", "spirvextensions", "spirvcapabilities", "sync", "videocodecs"):
            key = {"spirvextensions": "spirvExtensions", "spirvcapabilities": "spirvCapabilities",
                   "videocodecs": "videoCodecs"}.get(child.tag, child.tag)
            sections[key] = generic_collection(child)
    result["constants"] = constants
    result["enums"] = enums
    for key in ("platforms", "tags", "types", "commands", "features", "extensions",
                "formats", "spirvExtensions", "spirvCapabilities", "sync", "videoCodecs"):
        result[key] = sections.get(key, {})
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", default="vk.xml")
    ap.add_argument("--output", default="vk.json")
    ap.add_argument("--minify", action="store_true")
    ap.add_argument("--commit", default=None, help="upstream commit SHA")
    args = ap.parse_args()

    data = convert(args.input, args.commit)
    with open(args.output, "w", encoding="utf-8") as f:
        if args.minify:
            json.dump(data, f, separators=(",", ":"), ensure_ascii=False)
        else:
            json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"wrote {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
