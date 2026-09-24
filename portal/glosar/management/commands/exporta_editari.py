"""Scrie editările (ConceptEdit/RelationEdit) în fișierele curate. Spec §8.11.

    python manage.py exporta_editari [--dry-run]

Fișierele curate unificate sunt content/curated/concepts.tsv și relations.txt (dacă nu
există încă, se creează din părțile parts/*/). Conceptele generate de AI („Explică”) nu se
exportă decât cu --include-ai.
"""
import csv
import io
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from glosar import content as C
from glosar.models import ConceptEdit, RelationEdit

FIELDS = ["label", "level", "kind", "unit", "evidence", "definition", "aliases", "man"]


class Command(BaseCommand):
    help = "Exportă editările din aplicație în fișierele curate."

    def add_arguments(self, p):
        p.add_argument("--dry-run", action="store_true")
        p.add_argument("--include-ai", action="store_true", help="exportă și conceptele adăugate prin „Explică”")

    def handle(self, dry_run=False, include_ai=False, **kw):
        cur = Path(settings.PCLP_CONTENT).parents[0] / "curated"
        if not cur.exists():
            cur = settings.REPO / "content" / "curated"
        ctsv, rtxt = cur / "concepts.tsv", cur / "relations.txt"
        rows = self._read_rows(cur, ctsv)
        by_id = {C.concept_id(r["label"]): r for r in rows}
        changed = 0
        for e in ConceptEdit.objects.all():
            if e.origin == "claude" and not include_ai:
                continue
            r = by_id.get(e.concept_id)
            if r is None:
                r = {f: "" for f in FIELDS}
                rows.append(r)
                by_id[e.concept_id] = r
            if e.label:
                r["label"] = e.label
            if e.level:
                r["level"] = str(e.level)
            for f in ("kind", "unit", "definition"):
                if getattr(e, f):
                    r[f] = getattr(e, f)
            if e.man:
                r["man"] = e.man.replace(".", "(", 1) + ")" if "(" not in e.man and "." in e.man else e.man
            al = [a for a in r.get("aliases", "").split(";") if a.strip()]
            for a in e.extra_aliases or []:
                if a not in al:
                    al.append(a)
            r["aliases"] = ";".join(al)
            if e.def_location and ":" in e.def_location:
                uid, i = e.def_location.split(":")
                sec = C.section_of_block(uid, int(i))
                ev = [x for x in r.get("evidence", "").split(",") if x]
                if sec and f"{uid}#{sec}" not in ev:
                    r["evidence"] = ",".join([f"{uid}#{sec}"] + ev)
            changed += 1
        rel_lines = self._read_rel_lines(cur, rtxt)
        labels = {k: v["label"] for k, v in C.concepts().items()}
        hidden = {e.relation_id for e in RelationEdit.objects.filter(action="hide")}
        if hidden:
            dbrels = {r["id"]: r for r in C.q("SELECT * FROM relations")}
            drop = set()
            for rid in hidden:
                r = dbrels.get(rid)
                if r:
                    drop.add((labels.get(r["subj"]), r["pred"], labels.get(r["obj"])))
            rel_lines = [ln for ln in rel_lines if tuple(p.strip() for p in ln.split("|")[:3]) not in drop]
        for e in RelationEdit.objects.filter(action="add"):
            s, o = labels.get(e.subj), labels.get(e.obj)
            if s and o:
                rel_lines.append(f"{s}|{e.pred}|{o}||editorial")
                changed += 1
        out = io.StringIO()
        w = csv.DictWriter(out, fieldnames=FIELDS, delimiter="\t", lineterminator="\n", extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)
        if dry_run:
            self.stdout.write(f"[dry-run] {changed} modificări; {len(rows)} concepte, {len(rel_lines)} relații")
            return
        ctsv.write_text(out.getvalue(), encoding="utf-8")
        rtxt.write_text("\n".join(rel_lines) + "\n", encoding="utf-8")
        self.stdout.write(self.style.SUCCESS(f"Scris {ctsv} și {rtxt} ({changed} modificări). Reconstruiește baza cu content/pipeline/build.py."))

    def _read_rows(self, cur, ctsv):
        files = [ctsv] if ctsv.exists() else sorted((cur / "parts").glob("*/concepts.tsv"))
        rows, seen = [], set()
        for f in files:
            with f.open(encoding="utf-8") as fh:
                for r in csv.DictReader(fh, delimiter="\t"):
                    cid = C.concept_id(r["label"])
                    if cid not in seen:
                        seen.add(cid)
                        rows.append(r)
        return rows

    def _read_rel_lines(self, cur, rtxt):
        files = [rtxt] if rtxt.exists() else sorted((cur / "parts").glob("*/relations.txt"))
        lines = []
        for f in files:
            lines += [ln for ln in f.read_text(encoding="utf-8").splitlines() if ln.strip()]
        return lines
