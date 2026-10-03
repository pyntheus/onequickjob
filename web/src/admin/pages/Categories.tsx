import { Placeholder } from "../../shared/Placeholder";

/** Categories: placeholder until lane L3 builds it. Owned by L3. */
export default function Categories() {
  return (
    <Placeholder
      title="Categories"
      lane="L3"
      prototype="AdminCategories"
      endpoints={[
        "GET /api/admin/categories",
        "GET /api/admin/categories/{category_id}",
      ]}
    />
  );
}
