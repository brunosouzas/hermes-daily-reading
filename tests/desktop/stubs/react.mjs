export const useState = v => [v, () => {}]
export const useEffect = () => {}
export const useRef = v => ({ current: v })
export default { useState, useEffect, useRef }
