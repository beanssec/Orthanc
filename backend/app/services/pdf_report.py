"""Generate formatted PDF intelligence reports."""
import io
import re
from datetime import datetime
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
)
from reportlab.lib.enums import TA_CENTER, TA_LEFT

# Dark theme colors for PDF — professional intelligence aesthetic
DARK_BG = colors.HexColor('#0a0e1a')
SURFACE = colors.HexColor('#111827')
BORDER = colors.HexColor('#1f2937')
ACCENT = colors.HexColor('#3b82f6')
TEXT_PRIMARY = colors.HexColor('#f9fafb')
TEXT_MUTED = colors.HexColor('#9ca3af')


class OrthanIntelReport:
    def __init__(self):
        self.styles = getSampleStyleSheet()
        self._setup_styles()

    def _setup_styles(self):
        self.styles.add(ParagraphStyle(
            'ReportTitle',
            parent=self.styles['Heading1'],
            fontSize=24,
            textColor=TEXT_PRIMARY,
            spaceAfter=6,
            alignment=TA_CENTER,
            fontName='Helvetica-Bold',
        ))
        self.styles.add(ParagraphStyle(
            'Classification',
            parent=self.styles['Normal'],
            fontSize=10,
            textColor=colors.white,
            backColor=ACCENT,
            alignment=TA_CENTER,
            spaceAfter=12,
            spaceBefore=6,
            fontName='Helvetica-Bold',
            leading=18,
        ))
        self.styles.add(ParagraphStyle(
            'SectionHead',
            parent=self.styles['Heading2'],
            fontSize=13,
            textColor=ACCENT,
            spaceBefore=14,
            spaceAfter=6,
            fontName='Helvetica-Bold',
        ))
        self.styles.add(ParagraphStyle(
            'BodyText_Dark',
            parent=self.styles['Normal'],
            fontSize=10,
            textColor=TEXT_PRIMARY,
            leading=14,
            fontName='Helvetica',
            spaceAfter=4,
        ))
        self.styles.add(ParagraphStyle(
            'BulletText',
            parent=self.styles['Normal'],
            fontSize=10,
            textColor=TEXT_PRIMARY,
            leading=14,
            fontName='Helvetica',
            spaceAfter=3,
            leftIndent=12,
        ))
        self.styles.add(ParagraphStyle(
            'H3Text',
            parent=self.styles['Normal'],
            fontSize=11,
            textColor=TEXT_PRIMARY,
            leading=14,
            fontName='Helvetica-Bold',
            spaceAfter=4,
            spaceBefore=8,
        ))
        self.styles.add(ParagraphStyle(
            'MetaText',
            parent=self.styles['Normal'],
            fontSize=8,
            textColor=TEXT_MUTED,
            leading=10,
            alignment=TA_CENTER,
        ))

    def generate(
        self,
        brief: dict,
        entities: list = None,
        source_stats: dict = None,
    ) -> bytes:
        """Generate PDF report from a brief + optional context data.

        Args:
            brief: {summary, model, model_name, hours, cost_estimate, generated_at}
            entities: [{name, type, mentions}, ...] — top entities in the brief period
            source_stats: {source_type: count, ...} — post counts by source

        Returns:
            PDF bytes
        """
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            leftMargin=20 * mm,
            rightMargin=20 * mm,
            topMargin=15 * mm,
            bottomMargin=15 * mm,
        )

        story = []

        # Confidence banner (if present in brief data)
        confidence_label = brief.get("confidence_label")
        if confidence_label and confidence_label != "unrated":
            banner_color, banner_text = self._confidence_banner_style(confidence_label)
            conf_style = ParagraphStyle(
                'ConfidenceBanner',
                parent=self.styles['Normal'],
                fontSize=9,
                textColor=colors.white,
                backColor=banner_color,
                alignment=TA_CENTER,
                spaceAfter=4,
                spaceBefore=0,
                fontName='Helvetica-Bold',
                leading=16,
            )
            story.append(Paragraph(banner_text, conf_style))

        # Classification banner
        story.append(Paragraph("UNCLASSIFIED // OSINT", self.styles['Classification']))

        # Title
        story.append(Paragraph("INTELLIGENCE BRIEF", self.styles['ReportTitle']))
        story.append(Spacer(1, 4 * mm))

        # Metadata line
        generated = brief.get('generated_at', datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"))
        model = brief.get('model_name') or brief.get('model', 'Unknown')
        time_range = brief.get('hours', 24)
        post_count = brief.get('post_count', 0) or 0
        cost = brief.get('cost_estimate', '')
        cost_part = f" | Cost: {cost}" if cost else ""
        meta_text = (
            f"Generated: {generated}  |  Model: {model}  |  "
            f"Coverage: {time_range}h  |  Posts: {post_count}{cost_part}  |  Platform: Orthanc OSINT"
        )
        story.append(Paragraph(meta_text, self.styles['MetaText']))
        story.append(HRFlowable(width="100%", color=BORDER, thickness=1, spaceAfter=8))

        # Brief content — convert markdown to flowables
        content = brief.get('summary', '')
        story.extend(self._markdown_to_flowables(content))

        # Entity summary table (if provided and non-empty)
        if entities:
            story.append(Spacer(1, 6 * mm))
            story.append(Paragraph("KEY ENTITIES", self.styles['SectionHead']))

            table_data = [['Entity', 'Type', 'Mentions']]
            for e in entities[:20]:
                table_data.append([
                    str(e.get('name', '')),
                    str(e.get('type', '')),
                    str(e.get('mentions', '')),
                ])

            t = Table(table_data, colWidths=[80 * mm, 40 * mm, 30 * mm])
            t.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), SURFACE),
                ('TEXTCOLOR', (0, 0), (-1, 0), ACCENT),
                ('TEXTCOLOR', (0, 1), (-1, -1), TEXT_PRIMARY),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 9),
                ('BACKGROUND', (0, 1), (-1, -1), DARK_BG),
                ('GRID', (0, 0), (-1, -1), 0.5, BORDER),
                ('ALIGN', (2, 0), (2, -1), 'RIGHT'),
                ('TOPPADDING', (0, 0), (-1, -1), 4),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ]))
            story.append(t)

        # Confidence summary section (if present)
        confidence_summary = brief.get("confidence_summary")
        confidence_detail = brief.get("confidence_detail")
        if confidence_label or confidence_summary:
            story.append(Spacer(1, 6 * mm))
            story.append(Paragraph("SOURCE RELIABILITY & CONFIDENCE", self.styles['SectionHead']))
            if confidence_summary:
                story.append(Paragraph(
                    self._inline(confidence_summary),
                    self.styles['BodyText_Dark'],
                ))
            if confidence_detail:
                detail_rows = [['Metric', 'Value']]
                detail_map = {
                    'source_coverage': ('Source Coverage', lambda v: f"{int(v * 100)}%"),
                    'rated_post_count': ('Rated Posts', str),
                    'total_post_count': ('Total Posts', str),
                    'high_confidence_fraction': ('High-Reliability Fraction', lambda v: f"{int(v * 100)}%"),
                    'low_confidence_fraction': ('Low-Reliability Fraction', lambda v: f"{int(v * 100)}%"),
                    'conflicting_signals': ('Conflicting Signals', lambda v: '⚠ YES' if v else 'No'),
                    'early_signal': ('Early/Weak Signal', lambda v: '⚠ YES' if v else 'No'),
                }
                for key, (label_str, fmt) in detail_map.items():
                    if key in confidence_detail:
                        try:
                            detail_rows.append([label_str, fmt(confidence_detail[key])])
                        except Exception:
                            pass
                if len(detail_rows) > 1:
                    t = Table(detail_rows, colWidths=[90 * mm, 60 * mm])
                    t.setStyle(TableStyle([
                        ('BACKGROUND', (0, 0), (-1, 0), SURFACE),
                        ('TEXTCOLOR', (0, 0), (-1, 0), ACCENT),
                        ('TEXTCOLOR', (0, 1), (-1, -1), TEXT_PRIMARY),
                        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                        ('FONTSIZE', (0, 0), (-1, -1), 9),
                        ('BACKGROUND', (0, 1), (-1, -1), DARK_BG),
                        ('GRID', (0, 0), (-1, -1), 0.5, BORDER),
                        ('ALIGN', (1, 0), (1, -1), 'LEFT'),
                        ('TOPPADDING', (0, 0), (-1, -1), 4),
                        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
                    ]))
                    story.append(t)

        # Source breakdown (if provided and non-empty)
        if source_stats:
            story.append(Spacer(1, 6 * mm))
            story.append(Paragraph("SOURCE BREAKDOWN", self.styles['SectionHead']))

            table_data = [['Source Type', 'Posts Analyzed']]
            for src, count in sorted(source_stats.items(), key=lambda x: -x[1]):
                table_data.append([src.upper(), str(count)])

            t = Table(table_data, colWidths=[90 * mm, 60 * mm])
            t.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), SURFACE),
                ('TEXTCOLOR', (0, 0), (-1, 0), ACCENT),
                ('TEXTCOLOR', (0, 1), (-1, -1), TEXT_PRIMARY),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 9),
                ('BACKGROUND', (0, 1), (-1, -1), DARK_BG),
                ('GRID', (0, 0), (-1, -1), 0.5, BORDER),
                ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
                ('TOPPADDING', (0, 0), (-1, -1), 4),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ]))
            story.append(t)

        # Footer
        story.append(Spacer(1, 10 * mm))
        story.append(HRFlowable(width="100%", color=BORDER, thickness=1, spaceAfter=4))
        story.append(Paragraph(
            f"Orthanc Open Source Intelligence Platform — {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
            self.styles['MetaText'],
        ))
        story.append(Paragraph("UNCLASSIFIED // OSINT", self.styles['Classification']))

        doc.build(story, onFirstPage=self._add_bg, onLaterPages=self._add_bg)
        return buffer.getvalue()

    def _confidence_banner_style(self, label: str) -> tuple:
        """Return (background_color, banner_text) for a confidence label."""
        label_lower = label.lower()
        if "high" in label_lower:
            return colors.HexColor('#065f46'), f"SOURCE CONFIDENCE: {label.upper()}"
        if "conflict" in label_lower:
            return colors.HexColor('#92400e'), f"⚠ {label.upper()}"
        if "low" in label_lower or "early" in label_lower or "weak" in label_lower:
            return colors.HexColor('#7f1d1d'), f"⚠ {label.upper()}"
        # medium / default
        return colors.HexColor('#1e3a5f'), f"SOURCE CONFIDENCE: {label.upper()}"

    def _add_bg(self, canvas, doc):
        """Dark background on every page."""
        canvas.saveState()
        canvas.setFillColor(DARK_BG)
        canvas.rect(0, 0, A4[0], A4[1], fill=True, stroke=False)
        canvas.restoreState()

    def _markdown_to_flowables(self, text: str) -> list:
        """Convert markdown text to reportlab flowables."""
        flowables = []
        lines = text.split('\n')

        for line in lines:
            stripped = line.strip()

            if not stripped:
                flowables.append(Spacer(1, 2 * mm))
                continue

            if stripped.startswith('### '):
                flowables.append(Paragraph(
                    self._inline(stripped[4:]),
                    self.styles['H3Text'],
                ))
            elif stripped.startswith('## '):
                flowables.append(Paragraph(
                    self._inline(stripped[3:]),
                    self.styles['SectionHead'],
                ))
            elif stripped.startswith('# '):
                flowables.append(Paragraph(
                    self._inline(stripped[2:]),
                    self.styles['SectionHead'],
                ))
            elif stripped.startswith('- ') or stripped.startswith('* '):
                flowables.append(Paragraph(
                    '• ' + self._inline(stripped[2:]),
                    self.styles['BulletText'],
                ))
            elif re.match(r'^\d+\.', stripped):
                flowables.append(Paragraph(
                    self._inline(stripped),
                    self.styles['BodyText_Dark'],
                ))
            else:
                flowables.append(Paragraph(
                    self._inline(stripped),
                    self.styles['BodyText_Dark'],
                ))

        return flowables

    def _inline(self, text: str) -> str:
        """Convert inline markdown (bold, italic) to reportlab XML."""
        # Bold
        text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
        # Italic
        text = re.sub(r'\*(.+?)\*', r'<i>\1</i>', text)
        # Escape any stray ampersands that aren't already entities
        # (reportlab uses XML-like markup)
        text = re.sub(r'&(?!amp;|lt;|gt;|quot;|apos;|#)', '&amp;', text)
        return text


pdf_report = OrthanIntelReport()
