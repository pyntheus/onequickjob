import { Ban, BadgeCheck, Camera, Lock, MapPin, ShieldCheck, Sprout, Star, Users } from "lucide-react";
import { useState, type CSSProperties } from "react";
import { useNavigate } from "react-router";
import { useCategories } from "../../api/queries";
import { Avatar } from "../../shared/Avatar";
import { CatIcon } from "../../shared/CatIcon";
import { fmt } from "../../shared/format";
import { Loading } from "../../app/Status";
import { useFeeExample, type Category } from "../api";
import { GardenArt } from "../components/Art";
import { AddressSearch } from "../components/AddressSearch";
import { useFlow } from "../flow";

const g = (px: number) => ({ "--g": `${px}px` }) as CSSProperties;

function QuoteStarter() {
  const navigate = useNavigate();
  const { data: catalogue, isLoading, isError } = useCategories();
  const { flow, update } = useFlow();
  const cats = catalogue?.categories ?? [];
  const current = cats.find((c) => c.id === flow.categoryId) ?? cats[0];
  const [group, setGroup] = useState<string | null>(null);
  const shownGroup = group ?? current?.group ?? "outside";
  const groups = [...(catalogue?.groups ?? [])].sort((a, b) => a.sort - b.sort);
  const tiles = cats.filter((c) => c.group === shownGroup).sort((a, b) => a.sort - b.sort);
  const ready = !!current && !!flow.address;

  const start = (cat: Category) => navigate(`/quote/${cat.id}/${cat.measure ? "size" : "details"}`);

  return (
    <div className="card quote-card stack" style={g(18)}>
      <div className="stack" style={g(12)}>
        <span className="label" id="qs-what">
          What needs doing?
        </span>
        {isLoading && <Loading label="Loading the jobs we do…" />}
        {isError && <p className="field-error">We couldn't load the jobs just now. Please refresh.</p>}
        <div className="tabs" role="tablist" aria-label="Kind of job">
          {groups.map((gr) => (
            <button
              key={gr.id}
              type="button"
              role="tab"
              aria-selected={shownGroup === gr.id}
              className={shownGroup === gr.id ? "on" : ""}
              onClick={() => setGroup(gr.id ?? null)}
            >
              {gr.tab}
            </button>
          ))}
        </div>
        <div className="cat-tiles" role="group" aria-labelledby="qs-what">
          {tiles.map((c) => (
            <button
              key={c.id}
              type="button"
              aria-pressed={current?.id === c.id}
              className={"cat-tile" + (current?.id === c.id ? " on" : "")}
              onClick={() => update({ categoryId: c.id ?? "", quoteId: null })}
            >
              <span className="cat-ico">
                <CatIcon icon={c.icon} id={c.id} size={21} />
              </span>
              <span className="cat-name">{c.name}</span>
              <span className="xs muted">from {fmt(c.from_price_pence)}</span>
            </button>
          ))}
        </div>
      </div>
      <AddressSearch
        value={flow.addressText}
        onText={(t) => update((f) => ({ addressText: t, address: f.address && f.address.label === t ? f.address : null }))}
        onResolved={(a) => update({ address: a, addressText: a.label || flow.addressText, quoteId: null })}
      />
      <button
        type="button"
        className="btn btn-cta btn-lg btn-block"
        onClick={() => current && start(current)}
        disabled={!ready}
      >
        See my price
      </button>
      {!flow.address && flow.addressText.trim().length > 0 && (
        <p className="xs muted center">Choose your address from the list to see a price.</p>
      )}
      <p className="xs muted row" style={g(6)}>
        <Lock size={13} aria-hidden="true" /> No account needed to see a price. We don't pass your details on.
      </p>
    </div>
  );
}

function Hero() {
  return (
    <section className="hero-v">
      <div className="stack" style={g(22)}>
        <span className="kicker">High Wycombe, Marlow, Beaconsfield and Hazlemere</span>
        <h1 className="display">Home and garden jobs, done by people who live nearby.</h1>
        <p className="lead">
          Get a guide price in under a minute. Someone local picks the job up, and you only pay once it's done.
        </p>
        <QuoteStarter />
      </div>
      <div className="hero-art" aria-hidden="true">
        <GardenArt />
        <div className="float-card fc-1">
          <Avatar initials="DH" size={38} />
          <div className="stack" style={g(0)}>
            <span className="small" style={{ fontWeight: 600 }}>
              Dave H. took your job
            </span>
            <span className="xs muted">Lives 1.2 miles away</span>
          </div>
        </div>
        <div className="float-card fc-2">
          <span className="xs muted">Guide price</span>
          <span className="h3" style={{ fontFamily: "var(--font-head)" }}>
            £30 a visit
          </span>
        </div>
      </div>
    </section>
  );
}

const STEPS = [
  {
    icon: MapPin,
    title: "Get a guide price",
    // A6, A26: no claim that we measure anything. The customer picks a size, paces it out or gives it.
    text: "Answer a few quick questions. For lawns, you pick roughly how big yours is, or pace it out. No call-backs, no account.",
  },
  {
    icon: Users,
    title: "Someone local picks it up",
    text: "Providers near you accept the guide price or suggest their own. You approve any change before it's booked.",
  },
  {
    icon: Camera,
    title: "Pay when it's done",
    text: "You get before and after photos, then your card is charged. Rate the visit and rebook in a tap.",
  },
];

function HowItWorks() {
  return (
    <section className="c-section" aria-labelledby="how-title">
      <h2 className="h1 c-section-title" id="how-title">
        How it works
      </h2>
      <div className="grid3">
        {STEPS.map(({ icon: I, title, text }, i) => (
          <div key={title} className="card stack" style={g(10)}>
            <div className="row between">
              <span className="step-ico">
                <I size={20} aria-hidden="true" />
              </span>
              <span className="step-n">Step {i + 1}</span>
            </div>
            <h3 className="h3">{title}</h3>
            <p className="muted">{text}</p>
          </div>
        ))}
      </div>
    </section>
  );
}

const CHECKS = [
  {
    icon: BadgeCheck,
    title: "ID checked",
    text: "Every provider, before their first job. Anyone working inside your home also has a basic DBS check.",
  },
  {
    icon: ShieldCheck,
    title: "Insurance checked",
    text: "Public liability cover verified, and expiry dates tracked. Ladder and pet work need the right cover too.",
  },
  { icon: Star, title: "Rated after every visit", text: "Low ratings are followed up. Repeated problems mean removal." },
  { icon: MapPin, title: "Genuinely local", text: "Most live within a couple of miles of the jobs they take." },
];

function TrustAndFees() {
  const { data } = useFeeExample();
  const sp = data?.split;
  return (
    <section className="c-section split">
      <div className="card stack" style={g(16)}>
        <h2 className="h2">Who does the work</h2>
        <p className="muted">
          Retired tradespeople, experienced cleaners, keen gardeners and handy neighbours who want flexible work.
        </p>
        <div className="stack" style={g(14)}>
          {CHECKS.map(({ icon: I, title, text }) => (
            <div key={title} className="check-row">
              <span className="ci">
                <I size={18} aria-hidden="true" />
              </span>
              <div className="stack" style={g(1)}>
                <b>{title}</b>
                <span className="small muted">{text}</span>
              </div>
            </div>
          ))}
        </div>
      </div>
      <div className="card stack" style={g(16)}>
        <h2 className="h2">Where your money goes</h2>
        {sp && (
          <>
            <p className="muted">On a {fmt(sp.price_pence)} job:</p>
            <div className="fee-bar" aria-hidden="true">
              <i style={{ width: `${(sp.provider_pence / sp.price_pence) * 100}%` }} />
            </div>
            <div className="stack" style={g(8)}>
              <div className="row between">
                <span className="row" style={g(8)}>
                  <span className="dot dot-provider" aria-hidden="true" /> Your provider
                </span>
                <b>{fmt(sp.provider_pence)}</b>
              </div>
              <div className="row between">
                <span className="row" style={g(8)}>
                  <span className="dot dot-fee" aria-hidden="true" /> OneQuickJob fee ({sp.rate_percent}%)
                </span>
                <b>{fmt(sp.fee_pence)}</b>
              </div>
            </div>
          </>
        )}
        <div className="soft small">
          Your agreement is with the person doing the work. OneQuickJob arranges the booking, takes payment on their
          behalf through Stripe, and helps sort things out if something goes wrong.
        </div>
      </div>
    </section>
  );
}

function WhatWeDontDo() {
  const { data: catalogue } = useCategories();
  const excluded = [...(catalogue?.excluded ?? [])].sort((a, b) => a.sort - b.sort);
  if (!excluded.length) return null;
  return (
    <section className="c-section">
      <div className="card flat stack" style={g(18)}>
        <div className="stack" style={g(4)}>
          <h2 className="h2">What we don't do</h2>
          <p className="muted">
            Some jobs need a registered or licensed professional. We don't list them, so you're never matched with the
            wrong person.
          </p>
        </div>
        <div className="excluded">
          {excluded.map((x) => (
            <div key={x.id} className="ex-row">
              <span className="ex-ico">
                <Ban size={15} aria-hidden="true" />
              </span>
              <div className="stack" style={g(0)}>
                <b className="small">{x.name}</b>
                <span className="xs muted">Use {x.instead}.</span>
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

/** Home and quote: the Village hero with the quote starter, how it works, fees, what we don't do. */
export default function Landing() {
  return (
    <>
      <div className="c-wrap">
        <Hero />
        <HowItWorks />
        <TrustAndFees />
        <WhatWeDontDo />
      </div>
      <footer className="c-footer">
        <span className="brand sm">
          <span className="brand-mark" aria-hidden="true">
            <Sprout size={14} />
          </span>
          OneQuickJob
        </span>
        <p className="xs muted">Working in High Wycombe, Marlow, Beaconsfield, Penn, Hazlemere and Princes Risborough.</p>
        <p className="xs muted">Prototype, not a live service.</p>
      </footer>
    </>
  );
}
