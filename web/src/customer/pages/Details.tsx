import { Placeholder } from "../../shared/Placeholder";

/** Job questions: placeholder until lane L1 builds it. Owned by L1. */
export default function Details() {
  return (
    <div className="c-flow">
      <Placeholder
        title="Job questions"
        lane="L1"
        prototype="DetailsScreen and IntakeField"
        notes="Render every question generically from the category's intake schema."
        endpoints={[
          "GET /api/categories/{category_id}",
          "POST /api/files",
        ]}
      />
    </div>
  );
}
