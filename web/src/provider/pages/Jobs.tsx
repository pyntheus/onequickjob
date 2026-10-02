import { Placeholder } from "../../shared/Placeholder";

/** New jobs: placeholder until lane L2 builds it. Owned by L2. */
export default function Jobs() {
  return (
    <Placeholder
      title="New jobs"
      lane="L2"
      prototype="ProviderJobs, OfferCard and LimitStrip"
      notes="The prototype's “Text-message alert” screen (SmsScreen) is shown in the Outbox drawer instead: job alerts link to /p/j/{ref}."
      endpoints={[
        "GET /api/p/home",
        "GET /api/p/jobs",
      ]}
    />
  );
}
