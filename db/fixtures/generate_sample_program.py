#!/usr/bin/env python3
"""Rebuild Tristan's parser fixture: uv run --with reportlab this_file.py.

The companion JSON is the expected semantic result; parser notes may vary.
"""
import json
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak

HERE = Path(__file__).resolve().parent


def exercise(key, name, sets, reps, notes):
    return dict(exercise_key=key, name=name, sets=sets, reps=reps, notes=notes, supported=key is not None)


PROGRAM = {
    "title": "Tristan's Three-Day Foundation Program",
    "days": [
        {"day_number": 1, "title": "Full Body Foundations", "exercises": [
            exercise("squat", "Squats", 3, 10, "Bodyweight. Lower with control; stand tall. Rest 60 seconds."),
            exercise("pushup", "Pushups", 3, 8, "Keep a straight trunk and controlled lowering. Rest 60 seconds."),
            exercise("lunge", "Lunges", 2, 10, "Alternate legs; 10 total repetitions per set. Rest 60 seconds."),
            exercise("bicep_curl", "Bicep curls", 3, 12, "Light dumbbells. Side view; keep elbows still. Rest 60 seconds."),
            exercise(None, "Bench press", 3, 8, "Light barbell load with a spotter. Manual tracking. Rest 90 seconds."),
        ]},
        {"day_number": 2, "title": "Lower Body and Conditioning", "exercises": [
            exercise("jumping_jack", "Jumping jacks", 3, 20, "Land softly and move at a steady pace. Rest 45 seconds."),
            exercise("squat", "Bodyweight squats", 3, 12, "Smooth tempo and balanced feet. Rest 60 seconds."),
            exercise("lunge", "Alternating lunges", 3, 10, "10 total repetitions per set. Keep the front knee stable. Rest 60 seconds."),
            exercise(None, "Romanian deadlift", 3, 10, "Light dumbbells; hinge at the hips. Manual tracking. Rest 90 seconds."),
            exercise(None, "Standing calf raises", 2, 15, "Pause briefly at the top. Manual tracking. Rest 45 seconds."),
        ]},
        {"day_number": 3, "title": "Upper Body and Full Body Practice", "exercises": [
            exercise("pushup", "Push-ups", 3, 8, "Controlled range of motion and steady breathing. Rest 60 seconds."),
            exercise("bicep_curl", "Dumbbell biceps curls", 3, 12, "Side view; avoid swinging the torso. Rest 60 seconds."),
            exercise("squat", "Squats", 2, 10, "Easy bodyweight practice. Rest 60 seconds."),
            exercise(None, "Seated cable row", 3, 12, "Keep shoulders relaxed; pull with control. Manual tracking. Rest 75 seconds."),
            exercise("jumping_jack", "Jumping jacks", 2, 20, "Comfortable pace to finish. Rest 45 seconds."),
        ]},
    ],
}


def main():
    styles = getSampleStyleSheet()
    ink, teal, muted = colors.HexColor("#172E39"), colors.HexColor("#167B75"), colors.HexColor("#536773")
    styles.add(ParagraphStyle(name="ProgramTitle", fontName="Helvetica-Bold", fontSize=25, leading=30, textColor=ink, spaceAfter=14))
    styles.add(ParagraphStyle(name="DayTitle", fontName="Helvetica-Bold", fontSize=19, leading=24, textColor=ink, spaceAfter=12))
    styles.add(ParagraphStyle(name="Copy", fontName="Helvetica", fontSize=10, leading=15, textColor=muted, spaceAfter=12))
    styles.add(ParagraphStyle(name="Cell", fontName="Helvetica", fontSize=9, leading=13, textColor=ink, alignment=TA_LEFT))
    styles.add(ParagraphStyle(name="HeaderCell", parent=styles["Cell"], fontName="Helvetica-Bold", textColor=colors.white))
    story = []
    for index, day in enumerate(PROGRAM["days"]):
        if index:
            story.append(PageBreak())
        story.append(Paragraph("BRODIE FOR COACHES  /  SAMPLE PROGRAM", styles["Copy"]))
        story.append(Paragraph(escape(PROGRAM["title"]), styles["ProgramTitle"]))
        story.append(Paragraph("Coach: <b>Tristan</b> &nbsp; | &nbsp; Client: <b>Ryan</b> &nbsp; | &nbsp; 3 sessions per week", styles["Copy"]))
        story.append(Paragraph(f'Day {day["day_number"]}: {escape(day["title"])}', styles["DayTitle"]))
        story.append(Paragraph("Schedule on nonconsecutive days. Begin with 5 minutes of easy walking and comfortable joint movement. Choose a load that leaves 2 repetitions in reserve.", styles["Copy"]))
        rows = [[Paragraph(s, styles["HeaderCell"]) for s in ["EXERCISE", "SETS", "REPS", "COACH NOTES"]]]
        for ex in day["exercises"]:
            rows.append([Paragraph(escape(str(v)), styles["Cell"]) for v in [ex["name"], ex["sets"], ex["reps"], ex["notes"]]])
        table = Table(rows, colWidths=[1.7*inch, .65*inch, .65*inch, 4.1*inch], repeatRows=1)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), teal),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#F0F6F5"), colors.white]),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 12),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
            ("LEFTPADDING", (0, 0), (-1, -1), 9),
            ("RIGHTPADDING", (0, 0), (-1, -1), 9),
        ]))
        story.extend([table, Spacer(1, 18), Paragraph("<b>Tracking:</b> Brodie counts squats, pushups, lunges, jumping jacks and bicep curls. Other movements stay in your program for manual tracking. Repetitions are per set; lunges use total alternating repetitions.", styles["Copy"]), Paragraph("<b>After the session:</b> Walk easily for 3 minutes. Record how the final set felt and review your recap with Tristan before increasing the load.", styles["Copy"])])

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor("#D9E5E3"))
        canvas.line(.7*inch, .62*inch, 7.8*inch, .62*inch)
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(muted)
        canvas.drawString(.7*inch, .43*inch, "TRISTAN / FOUNDATION PROGRAM / DEMO FIXTURE")
        canvas.drawRightString(7.8*inch, .43*inch, f"{doc.page} / 3")
        canvas.restoreState()

    SimpleDocTemplate(str(HERE / "sample_program.pdf"), pagesize=(8.5*inch, 11*inch), rightMargin=.7*inch, leftMargin=.7*inch, topMargin=.65*inch, bottomMargin=.85*inch, title=PROGRAM["title"], author="Coach Tristan", invariant=1).build(story, onFirstPage=footer, onLaterPages=footer)
    (HERE / "sample_program.expected.json").write_text(json.dumps(PROGRAM, indent=2) + "\n")
    print("Created sample_program.pdf and sample_program.expected.json")


if __name__ == "__main__":
    main()
