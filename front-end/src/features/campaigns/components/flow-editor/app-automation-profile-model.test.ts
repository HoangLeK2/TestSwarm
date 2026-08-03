import assert from 'node:assert/strict';
import test from 'node:test';

import {
  addLocator,
  addPopupWatcher,
  appAutomationProfile,
  csvToList,
  getLoginSetupStatus,
  listToCsv,
  patchFormField,
  patchLocator,
  patchLoginField,
  patchPostSubmitLoginField,
  patchLoginRecipe,
  patchLoginTarget
  // @ts-expect-error Node --experimental-strip-types test files import TS sources by extension.
} from './app-automation-profile-model.ts';

test('csv helpers trim empty items', () => {
  assert.deepEqual(csvToList(' Home, Profile, ,'), ['Home', 'Profile']);
  assert.equal(listToCsv(['Home', 'Profile']), 'Home, Profile');
});

test('profile model edits login locators and references', () => {
  let step: any = {
    type: 'login_if_needed',
    profile: { package: 'com.example.app', semantic_locators: {} }
  };

  step = addLocator(step);
  const name = Object.keys(step.profile.semantic_locators)[0];
  step = patchLocator(step, name, {
    resource_id_contains: 'username',
    target_class: 'android.widget.EditText'
  });
  step = patchLoginField(step, 'username', {
    locator: name,
    value_from: 'account.username'
  });
  step = patchLoginRecipe(step, {
    detect_logged_in: { any_text: ['Home'] },
    submit: { tap_text_any: ['Login'] }
  });

  const profile = appAutomationProfile(step);
  assert.equal(profile.package, 'com.example.app');
  assert.equal(
    profile.semantic_locators?.[name].candidates?.[0].resource_id_contains,
    'username'
  );
  assert.equal(profile.login_recipe?.fields?.username.locator, name);
  assert.equal(
    profile.login_recipe?.fields?.username.value_from,
    'account.username'
  );
  assert.deepEqual(profile.login_recipe?.detect_logged_in?.any_text, ['Home']);
});

test('profile model edits form recipes and watchers', () => {
  let step: any = {
    type: 'fill_form',
    recipe: 'basic',
    profile: {
      package: 'com.example.app',
      semantic_locators: {
        email_field: { candidates: [{ resource_id_contains: 'email' }] }
      },
      form_recipes: {}
    }
  };

  step = patchFormField(step, 'basic', 'email', {
    locator: 'email_field',
    value_from: 'variables.email',
    required: true
  });
  step = addPopupWatcher(step);

  const profile = appAutomationProfile(step);
  assert.equal(
    profile.form_recipes?.basic.fields?.email.locator,
    'email_field'
  );
  assert.equal(
    profile.form_recipes?.basic.fields?.email.value_from,
    'variables.email'
  );
  assert.equal(profile.popup_watchers?.[0].name, 'watcher_1');
  assert.deepEqual(profile.popup_watchers?.[0].action?.tap_text_any, [
    'Later',
    'Not now'
  ]);
});

test('login setup status only reports ready from persisted valid config', () => {
  const emptyStep: any = {
    type: 'login_if_needed',
    profile: {
      package: '',
      semantic_locators: {},
      login_recipe: {
        detect_logged_in: { any_text: [] },
        fields: {},
        submit: { tap_text_any: ['Login', 'Sign in'] }
      }
    }
  };

  assert.deepEqual(getLoginSetupStatus(emptyStep), {
    ready: false,
    configuredFieldCount: 0,
    missing: ['package', 'loggedInSignal', 'username', 'password']
  });

  let configuredStep = {
    ...emptyStep,
    profile: {
      ...emptyStep.profile,
      package: 'com.facebook.katana',
      login_recipe: {
        ...emptyStep.profile.login_recipe,
        detect_logged_in: { any_text: ['Trang chủ'] }
      }
    }
  };
  configuredStep = patchLoginTarget(configuredStep, 'username', {
    resource_id_contains: 'email'
  }) as any;
  configuredStep = patchLoginTarget(configuredStep, 'password', {
    resource_id_contains: 'password'
  }) as any;

  assert.deepEqual(getLoginSetupStatus(configuredStep), {
    ready: true,
    configuredFieldCount: 2,
    missing: []
  });
  assert.equal(
    configuredStep.profile.login_recipe.fields.username.value_from,
    'account.username'
  );
  assert.equal(
    configuredStep.profile.login_recipe.fields.password.value_from,
    'account.password'
  );
});

test('login model configures optional post-submit auth code without affecting readiness', () => {
  let step: any = {
    type: 'login_if_needed',
    profile: {
      package: 'com.example.app',
      semantic_locators: {
        username_field: { candidates: [{ resource_id_contains: 'email' }] },
        password_field: { candidates: [{ resource_id_contains: 'password' }] }
      },
      login_recipe: {
        detect_logged_in: { any_text: ['Home'] },
        fields: {
          username: {
            locator: 'username_field',
            value_from: 'account.username'
          },
          password: {
            locator: 'password_field',
            value_from: 'account.password'
          }
        },
        submit: { tap_text_any: ['Login'] }
      }
    }
  };

  step = patchLoginTarget(step, 'auth_code', {
    resource_id_contains: 'approvals_code'
  }) as any;
  step = patchPostSubmitLoginField(step, 'auth_code', {
    value_from: 'account.totp_code',
    required: false
  }) as any;

  assert.deepEqual(getLoginSetupStatus(step), {
    ready: true,
    configuredFieldCount: 2,
    missing: []
  });
  assert.equal(
    step.profile.login_recipe.post_submit_fields.auth_code.value_from,
    'account.totp_code'
  );
  assert.equal(
    step.profile.login_recipe.post_submit_fields.auth_code.required,
    false
  );
  assert.deepEqual(step.profile.login_recipe.post_submit.tap_text_any, [
    'Continue',
    'Next',
    'Tiếp tục'
  ]);
});

test('editing the basic locator preserves advanced candidates', () => {
  const step: any = {
    type: 'login_if_needed',
    profile: {
      semantic_locators: {
        login_username: {
          min_score: 0.8,
          candidates: [
            { resource_id_contains: 'old-email' },
            { description_contains: 'Email address' }
          ]
        }
      }
    }
  };

  const next = patchLocator(step, 'login_username', {
    resource_id_contains: 'email'
  });

  assert.equal(
    (next.profile as any).semantic_locators.login_username.min_score,
    0.8
  );
  assert.deepEqual(
    (next.profile as any).semantic_locators.login_username.candidates,
    [
      { resource_id_contains: 'email' },
      { description_contains: 'Email address' }
    ]
  );
});

test('login readiness inherits valid advanced locator candidates', () => {
  const step: any = {
    type: 'login_if_needed',
    profile: {
      package: 'com.example.app',
      semantic_locators: {
        username_field: {
          candidates: [
            { class_name: 'android.widget.EditText' },
            { description_contains: 'Email address' }
          ]
        },
        password_field: {
          candidates: [{ description_contains: 'Password' }]
        }
      },
      login_recipe: {
        detect_logged_in: { any_text: ['Home'] },
        fields: {
          username: {
            locator: 'username_field',
            value_from: 'account.username'
          },
          password: {
            locator: 'password_field',
            value_from: 'secret.login_password'
          }
        },
        submit: { tap_text_any: ['Login'] }
      }
    }
  };

  assert.deepEqual(getLoginSetupStatus(step), {
    ready: true,
    configuredFieldCount: 2,
    missing: []
  });
});

test('clearing a simple login target detaches the field without corrupting its locator', () => {
  const step: any = {
    type: 'login_if_needed',
    profile: {
      semantic_locators: {
        username_field: {
          candidates: [{ resource_id_contains: 'email' }]
        }
      },
      login_recipe: {
        detect_logged_in: { any_text: ['Home'] },
        fields: {
          username: {
            locator: 'username_field',
            value_from: 'account.username'
          }
        },
        submit: { tap_text_any: ['Login'] }
      }
    }
  };

  const next = patchLoginTarget(step, 'username', {
    resource_id_contains: ''
  }) as any;

  assert.equal(next.profile.login_recipe.fields.username, undefined);
  assert.deepEqual(next.profile.semantic_locators.username_field.candidates, [
    { resource_id_contains: 'email' }
  ]);
  assert.doesNotMatch(JSON.stringify(next), /\"resource_id_contains\":\"\"/);
});
