import React from "react";

// Renders the small markdown subset used by the policy editor (# / ## / ###
// headings, "- " bullets, **bold**, blank-line paragraphs) as React
// elements. Deliberately no HTML passthrough: policy text is admin-edited
// and must never become markup.

const EMAIL_RE = /([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})/g;

function renderText(text: string, keyPrefix: string) {
  return text.split(EMAIL_RE).map((part, i) =>
    i % 2 === 1 ? (
      <a key={`${keyPrefix}-${i}`} href={`mailto:${part}`} className="text-brand-600 hover:underline">
        {part}
      </a>
    ) : (
      <React.Fragment key={`${keyPrefix}-${i}`}>{part}</React.Fragment>
    )
  );
}

function renderInline(text: string, keyPrefix: string) {
  return text.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
    part.startsWith("**") && part.endsWith("**") && part.length > 4 ? (
      <strong key={`${keyPrefix}-${i}`} className="font-semibold text-slate-900">
        {renderText(part.slice(2, -2), `${keyPrefix}-${i}`)}
      </strong>
    ) : (
      <React.Fragment key={`${keyPrefix}-${i}`}>{renderText(part, `${keyPrefix}-${i}`)}</React.Fragment>
    )
  );
}

export default function LegalMarkdown({ body }: { body: string }) {
  const blocks: React.ReactNode[] = [];
  let paragraph: string[] = [];
  let bullets: string[] = [];

  const flushParagraph = () => {
    if (paragraph.length) {
      const k = `p${blocks.length}`;
      blocks.push(<p key={k} className="text-sm leading-relaxed text-slate-600">{renderInline(paragraph.join(" "), k)}</p>);
      paragraph = [];
    }
  };
  const flushBullets = () => {
    if (bullets.length) {
      const k = `ul${blocks.length}`;
      blocks.push(
        <ul key={k} className="list-disc ps-5 space-y-1.5 text-sm leading-relaxed text-slate-600">
          {bullets.map((b, i) => <li key={i}>{renderInline(b, `${k}-${i}`)}</li>)}
        </ul>
      );
      bullets = [];
    }
  };

  for (const raw of body.replace(/\r\n/g, "\n").split("\n")) {
    const line = raw.trim();
    const heading = line.match(/^(#{1,3})\s+(.*)$/);
    if (!line) {
      flushParagraph();
      flushBullets();
    } else if (heading) {
      flushParagraph();
      flushBullets();
      const k = `h${blocks.length}`;
      const level = heading[1].length;
      blocks.push(
        level === 1 ? (
          <h2 key={k} className="text-xl font-bold text-slate-900 pt-4">{renderInline(heading[2], k)}</h2>
        ) : level === 2 ? (
          <h3 key={k} className="text-base font-bold text-slate-900 pt-4">{renderInline(heading[2], k)}</h3>
        ) : (
          <h4 key={k} className="text-sm font-bold text-slate-900 pt-2">{renderInline(heading[2], k)}</h4>
        )
      );
    } else if (/^[-*]\s+/.test(line)) {
      flushParagraph();
      bullets.push(line.replace(/^[-*]\s+/, ""));
    } else {
      flushBullets();
      paragraph.push(line);
    }
  }
  flushParagraph();
  flushBullets();

  return <div className="space-y-3">{blocks}</div>;
}
