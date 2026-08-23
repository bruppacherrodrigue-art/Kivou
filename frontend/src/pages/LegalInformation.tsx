import { Fragment } from 'react'
import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { PublicPageMeta } from '../components/PublicPageMeta'
import { SectionHeading } from '../components/Surfaces'
import { legalContent } from '../content/legalContent'
import type { LegalBlock } from '../content/legalContent'
import { useI18n } from '../i18n'
import styles from './LegalInformation.module.css'

const CONTACT_EMAIL = 'contact@kivou.eu'
const INLINE_TOKEN = /(`[^`]+`|contact@kivou\.eu)/g

export function LegalInformation() {
  const { locale } = useI18n()
  const content = legalContent[locale]

  return (
    <>
      <PublicPageMeta
        title={content.metaTitle}
        description={content.metaDescription}
        canonicalPath="/informations-legales"
      />

      <article className={styles.page}>
        <header className={styles.hero} id="sommaire" tabIndex={-1}>
          <div className={styles.heroInner}>
            <SectionHeading
              level={1}
              eyebrow={content.eyebrow}
              title={content.title}
              lead={content.introduction}
            />
            <p className={styles.updated}>{content.updated}</p>

            <nav className={styles.contents} aria-label={content.contentsLabel}>
              <ol>
                {content.contents.map((item, index) => (
                  <li key={item.id}>
                    <Link to={`/informations-legales#${item.id}`}>
                      <span aria-hidden="true">{String(index + 1).padStart(2, '0')}</span>
                      {item.label}
                    </Link>
                  </li>
                ))}
              </ol>
            </nav>
          </div>
        </header>

        <div className={styles.document}>
          {content.sections.map((section, index) => (
            <section
              key={section.id}
              id={section.id}
              tabIndex={-1}
              className={styles.legalSection}
              aria-labelledby={`${section.id}-title`}
            >
              <div className={styles.sectionNumber} aria-hidden="true">
                {String(index + 1).padStart(2, '0')}
              </div>
              <div className={styles.sectionBody}>
                <h2 id={`${section.id}-title`}>{section.title}</h2>
                {section.subsections.map((subsection) => (
                  <div className={styles.subsection} key={subsection.title}>
                    <h3>{subsection.title}</h3>
                    {subsection.blocks.map((block, blockIndex) => (
                      <LegalBlockView block={block} key={`${subsection.title}-${blockIndex}`} />
                    ))}
                  </div>
                ))}
                <a className={styles.backLink} href="#sommaire">
                  {content.backToContents}
                </a>
              </div>
            </section>
          ))}
        </div>
      </article>
    </>
  )
}

function LegalBlockView({ block }: { block: LegalBlock }) {
  if (block.kind === 'list') {
    return (
      <ul>
        {block.items.map((item) => (
          <li key={item}>
            <InlineLegalText text={item} />
          </li>
        ))}
      </ul>
    )
  }

  if (block.kind === 'address') {
    return (
      <address>
        {block.lines.map((line, index) => (
          <Fragment key={line}>
            <InlineLegalText text={line} />
            {index < block.lines.length - 1 ? <br /> : null}
          </Fragment>
        ))}
      </address>
    )
  }

  return (
    <p>
      <InlineLegalText text={block.text} />
    </p>
  )
}

function InlineLegalText({ text }: { text: string }) {
  const parts = text.split(INLINE_TOKEN)
  const nodes: ReactNode[] = parts.map((part, index) => {
    if (part === CONTACT_EMAIL) {
      return (
        <a href={`mailto:${CONTACT_EMAIL}`} key={`${part}-${index}`}>
          {part}
        </a>
      )
    }
    if (part.startsWith('`') && part.endsWith('`')) {
      return <code key={`${part}-${index}`}>{part.slice(1, -1)}</code>
    }
    return part
  })
  return <>{nodes}</>
}
