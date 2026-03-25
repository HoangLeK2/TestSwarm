Object.defineProperty(exports, Symbol.toStringTag, { value: 'Module' });

const core = require('@sentry/core');
const chalk = require('chalk');
const path = require('path');

/**
 * Construct a Turbopack config object from a Next.js config object and a Turbopack options object.
 *
 * @param userNextConfig - The Next.js config object.
 * @param turbopackOptions - The Turbopack options object.
 * @returns The Turbopack config object.
 */
function constructTurbopackConfig({
  userNextConfig,
  routeManifest,
}

) {
  const newConfig = {
    ...userNextConfig.turbopack,
  };

  if (routeManifest) {
    newConfig.rules = safelyAddTurbopackRule(newConfig.rules, {
      matcher: '**/instrumentation-client.*',
      rule: {
        loaders: [
          {
            loader: path.resolve(__dirname, '..', 'loaders', 'valueInjectionLoader.js'),
            options: {
              values: {
                _sentryRouteManifest: JSON.stringify(routeManifest),
              },
            },
          },
        ],
      },
    });
  }

  return newConfig;
}

/**
 * Safely add a Turbopack rule to the existing rules.
 *
 * @param existingRules - The existing rules.
 * @param matcher - The matcher for the rule.
 * @param rule - The rule to add.
 * @returns The updated rules object.
 */
function safelyAddTurbopackRule(
  existingRules,
  { matcher, rule },
) {
  if (!existingRules) {
    return {
      [matcher]: rule,
    };
  }

  // If the rule already exists, we don't want to mess with it.
  if (existingRules[matcher]) {
    core.debug.log(
      `${chalk.cyan(
        'info',
      )} - Turbopack rule already exists for ${matcher}. Please remove it from your Next.js config in order for Sentry to work properly.`,
    );
    return existingRules;
  }

  return {
    ...existingRules,
    [matcher]: rule,
  };
}

exports.constructTurbopackConfig = constructTurbopackConfig;
exports.safelyAddTurbopackRule = safelyAddTurbopackRule;
//# sourceMappingURL=constructTurbopackConfig.js.map
