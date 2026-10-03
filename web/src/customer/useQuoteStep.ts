/** The category a /quote/:categoryId/* screen is for, and the flow's navigation. */
import { useEffect } from "react";
import { useNavigate, useParams } from "react-router";
import { useCategories } from "../api/queries";
import { stepsFor, useFlow } from "./flow";

export function useQuoteStep(step: string) {
  const { categoryId = "" } = useParams();
  const navigate = useNavigate();
  const { data: catalogue, isLoading } = useCategories();
  const flowCtx = useFlow();
  const cat = catalogue?.categories.find((c) => c.id === categoryId) ?? null;
  const { flow, update } = flowCtx;

  useEffect(() => {
    if (cat && flow.categoryId !== cat.id) update({ categoryId: cat.id, quoteId: null });
  }, [cat, flow.categoryId, update]);

  const steps = cat ? stepsFor(cat) : [];
  const go = (to: string) => navigate(to === "landing" ? "/" : `/quote/${categoryId}/${to}`);
  const back = () => {
    const i = steps.indexOf(step);
    go(i > 0 ? steps[i - 1] : "landing");
  };
  return { ...flowCtx, cat, steps, go, back, loading: isLoading, unknown: !isLoading && !cat };
}
