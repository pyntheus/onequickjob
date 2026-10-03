import { Placeholder } from "../../shared/Placeholder";

/** Home and quote: placeholder until lane L1 builds it. Owned by L1. */
export default function Landing() {
  return (
    <div className="c-wrap" style={{ paddingTop: 24 }}>
      <Placeholder
        title="Home and quote"
        lane="L1"
        prototype="Landing (HeroVillage, QuoteStarter, HowItWorks, TrustAndFees, WhatWeDontDo)"
        notes="Group tabs and tiles come from the categories API; the excluded list too."
        endpoints={[
          "GET /api/categories",
          "GET /api/config",
          "GET /api/address/search?q=",
          "GET /api/address/{id}",
        ]}
      />
    </div>
  );
}
